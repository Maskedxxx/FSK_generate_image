// Слой 3, Нода 2: Рендер с двух сторон для каждой комнаты (параллельно)
// Вход: $l3_data (объект от ноды 1)
// ИНСАЙТ: Promise.all по комнатам И по сторонам — иначе упирается в таймаут nginx
// Артефакты: 10 prepared (Python /rotate) + 10 renders (Gemini Image) = 20 файлов на 5 комнат
// Статус: ПРОТЕСТИРОВАНО ✅

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

const ANGLE_PROMPT = `На изображении — часть интерьера комнаты (вид сверху). Точка съёмки рендера направление ТАК ЖЕ СВЕРХУ ВНИЗ но УГОЛ СЬЕМКИ немного ниже на 20 градусов!.

Сгенерируй фото этого помещения опустив камеру немного вниз и сьемка от угла ОТ ВАС в верхний ДАЛЬНИЙ угол сторону на уровне глаз — как будто камера стоит в ближнем углу стороне и фотографируешь дальний сторону угол.

Правила ОБЯЗАТЕЛЬНЫЕ К СОБЛЮДЕНИЯ РЕНДЕРА:
- область от нижнего стороны угла до верхнего стороны угла должна поместиться в кадр
- УЧИТЫВАЙ ГЕОМЕТРИЮ РЕФЕРЕНСА комнаты и ГЕОМЕТРИЮ пропорции И РАСПОЛОДЖЕНИИ мебели и артефактов с РЕФЕРЕНСА — не искажай размеры местоположение и форму
- предметы мебели СТРОГО на своих местах, как на референсе со стороны ОТ БЛИЖНЕЙ ВАС СТОРОНЫ К ДАЛЬНЕЙ СТОРОНЕ ДАЛЬНЕГО от ВАС — не перемещай и не добавляй
- Мебель и ВСЕ артефакты строго как на референсе, без добавлений и выдумок
- Не добавляй ничего нового — только то что видно на изображении
- Фотореализм, горизонтальный кадр на уровне глаз
- Без текста, надписей, водяных знаков, без букв-якорей`;

// Рендер одной стороны (a или b) для одной комнаты
async function renderSide(room, side) {
    const safeName = room.safe_name;
    const roomName = room.name;

    try {
        // 1. Готовим референс через Python /rotate (апскейл + поворот по стороне)
        const rotateResp = await axios.post('https://llm-home.fsk.fvds.ru/rotate', {
            s3_key: room.s3_key,
            task_id: data.task_id,
            room_name: roomName,
            side: side  // "a" — авто-угол, "b" — авто+180
        }, { timeout: 60000 });

        const preparedKey = rotateResp.data.s3_key;
        const angle = rotateResp.data.angle;

        // 2. Скачиваем подготовленный prepared из S3
        const prepResp = await s3.send(new GetObjectCommand({
            Bucket: 'fsk-service',
            Key: preparedKey
        }));
        const prepBytes = await prepResp.Body.transformToByteArray();
        const prepBase64 = Buffer.from(prepBytes).toString('base64');

        // 3. Контекст комнаты — добавим к промпту analysis
        let prompt = ANGLE_PROMPT;
        const roomAnalysis = (data.analysis.rooms.find(r => (r.name || 'unknown') === roomName) || {}).analysis;
        if (roomAnalysis) prompt += '\n\nRoom context:\n' + roomAnalysis;

        const content = [
            { type: "text", text: prompt },
            { type: "image_url", image_url: { url: "data:image/png;base64," + prepBase64 } }
        ];

        // 4. Gemini Image
        const response = await axios.post("https://openrouter.ai/api/v1/chat/completions", {
            model: "google/gemini-3.1-flash-image-preview",
            messages: [{ role: "user", content: content }],
            temperature: 1
        }, {
            headers: {
                "Authorization": "Bearer <OPENROUTER_API_KEY>",
                "Content-Type": "application/json"
            },
            timeout: 120000
        });

        // 5. Извлекаем base64 из ответа
        const message = response.data.choices[0].message;
        let imgBase64 = null;
        if (message.images && message.images.length > 0) {
            const url = message.images[0].image_url.url;
            imgBase64 = url.includes('base64,') ? url.split('base64,')[1] : url;
        } else if (message.content && message.content.includes('base64,')) {
            imgBase64 = message.content.split('base64,')[1].split(')')[0];
        }

        if (!imgBase64) return { name: roomName, side: side, error: 'no image' };

        // 6. Сохраняем рендер в S3
        const renderKey = 'fsk-generate-image/' + data.task_id + '/L3_renders/' + safeName + '_side_' + side + '.png';
        await s3.send(new PutObjectCommand({
            Bucket: 'fsk-service',
            Key: renderKey,
            Body: Buffer.from(imgBase64, 'base64'),
            ContentType: 'image/png'
        }));

        return { name: roomName, side: side, angle: angle, prepared_key: preparedKey, render_key: renderKey };
    } catch(e) {
        return { name: roomName, side: side, error: String(e).substring(0, 200) };
    }
}

// Запускаем ВСЁ параллельно: 5 комнат × 2 стороны = 10 одновременных задач
const tasks = [];
for (const room of data.refs) {
    if (!room.s3_key) continue; // нет референса — пропускаем
    tasks.push(renderSide(room, 'a'));
    tasks.push(renderSide(room, 'b'));
}
const results = await Promise.all(tasks);

return {
    task_id: data.task_id,
    renders: results
};
