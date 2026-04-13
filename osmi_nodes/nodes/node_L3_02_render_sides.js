// Слой 3, Нода 2: Рендер с двух сторон для каждой комнаты (параллельно)
// Вход: $l3_data (объект от ноды 1 через Set Variable)

const axios = require('axios');
const { S3Client, GetObjectCommand, PutObjectCommand } = require('@aws-sdk/client-s3');

const data = $l3_data;

const s3 = new S3Client({
   endpoint: 'https://storage.yandexcloud.net',
   region: 'us-east-1',
   credentials: {
         accessKeyId: '<S3_ACCESS_KEY_ID>',
         secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
   }
});

const PROMPT = `На изображении — часть интерьера комнаты (вид сверху). Точка съёмки рендера направление ТАК ЖЕ СВЕРХУ ВНИЗ но УГОЛ СЬЕМКИ немного ниже
на 20 градусов!.

Сгенерируй фото этого помещения опустив камеру немного вниз и сьемка от угла ОТ ВАС в верхний ДАЛЬНИЙ угол сторону на уровне глаз — как будто камера
стоит в ближнем углу стороне и фотографируешь дальний сторону угол.

Правила ОБЯЗАТЕЛЬНЫЕ К СОБЛЮДЕНИЯ РЕНДЕРА:
- область от нижнего стороны угла до верхнего стороны угла должна поместиться в кадр
- УЧИТЫВАЙ ГЕОМЕТРИЮ РЕФЕРЕНСА комнаты и ГЕОМЕТРИЮ пропорции И РАСПОЛОДЖЕНИИ мебели и артефактов с РЕФЕРЕНСА — не искажай размеры местоположение и
форму
- предметы мебели СТРОГО на своих местах, как на референсе со стороны ОТ БЛИЖНЕЙ ВАС СТОРОНЫ К ДАЛЬНЕЙ СТОРОНЕ ДАЛЬНЕГО от ВАС — не перемещай и не
добавляй
- Мебель и ВСЕ артефакты строго как на референсе, без добавлений и выдумок
- Не добавляй ничего нового — только то что видно на изображении
- Фотореализм, горизонтальный кадр на уровне глаз
- Без текста, надписей, водяных знаков, без букв-якорей`;

async function generateSide(prepBase64) {
   const response = await axios.post("https://openrouter.ai/api/v1/chat/completions", {
         model: "google/gemini-3.1-flash-image-preview",
         messages: [{ role: "user", content: [
            { type: "text", text: PROMPT },
            { type: "image_url", image_url: { url: "data:image/png;base64," + prepBase64 } }
         ]}],
         temperature: 1
   }, {
         headers: {
            "Authorization": "Bearer <OPENROUTER_API_KEY>",
            "Content-Type": "application/json"
         },
         timeout: 120000
   });
   const msg = response.data.choices[0].message;
   if (msg.images && msg.images.length > 0) {
         const url = msg.images[0].image_url.url;
         return url.includes('base64,') ? url.split('base64,')[1] : url;
   } else if (msg.content && msg.content.includes('base64,')) {
         return msg.content.split('base64,')[1].split(')')[0];
   }
   return null;
}

async function doSide(refKey, roomName, safeName, sideLabel) {
   try {
         const rot = await axios.post('https://llm-home.fsk.fvds.ru/rotate', {
            s3_key: refKey, task_id: data.task_id, room_name: roomName, side: sideLabel
         }, { timeout: 60000 });

         const prep = await s3.send(new GetObjectCommand({ Bucket: 'fsk-service', Key: rot.data.s3_key }));
         const prepBytes = await prep.Body.transformToByteArray();
         const prepBase64 = Buffer.from(prepBytes).toString('base64');

         const imgBase64 = await generateSide(prepBase64);
         if (!imgBase64) return { name: roomName, side: sideLabel, error: 'no image' };

         const key = 'fsk-generate-image/' + data.task_id + '/L3_renders/' + safeName + '_side_' + sideLabel + '.png';
         await s3.send(new PutObjectCommand({
            Bucket: 'fsk-service', Key: key,
            Body: Buffer.from(imgBase64, 'base64'), ContentType: 'image/png'
         }));
         return { name: roomName, side: sideLabel, s3_key: key };
   } catch(e) {
         return { name: roomName, side: sideLabel, error: String(e).substring(0, 200) };
   }
}

async function processRoom(room) {
   const roomName = room.name || 'unknown';
   const safeName = roomName.replace(/ /g, '_').replace(/\//g, '-');
   const refKey = data.ref_keys.find(k => k.includes(safeName + '.png'));
   if (!refKey) return [{ name: roomName, error: 'ref not found' }];

   // Параллельно side_a и side_b
   const [sideA, sideB] = await Promise.all([
         doSide(refKey, roomName, safeName, 'a'),
         doSide(refKey, roomName, safeName, 'b')
   ]);
   return [sideA, sideB];
}

// Все комнаты параллельно
const promises = data.analysis.rooms.map(room => processRoom(room));
const allResults = await Promise.all(promises);
const savedRenders = allResults.flat();

return {
   task_id: data.task_id,
   renders: savedRenders
};
