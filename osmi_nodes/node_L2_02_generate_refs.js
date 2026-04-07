// Слой 2, Нода 2: Генерация референсов сверху с мебелью (параллельно все комнаты)
// Вход: $l2_data (объект от ноды 1)
// ИНСАЙТ: Promise.all по комнатам — иначе упирается в таймаут nginx (60-240 сек)
// Статус: ПРОТЕСТИРОВАНО ✅ (5 референсов за ~30 сек параллельно)

const axios = require('axios');
const { S3Client, GetObjectCommand, PutObjectCommand } = require('@aws-sdk/client-s3');

const data = $l2_data;

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

const SYSTEM_PROMPT = `You are a professional interior designer. You receive a cropped floor plan of a single room (top-down view, THIS IS THE REFERENCE!) and client preferences.

Your task — generate a photorealistic interior image of this room.

Rules:
- FIRST PRIORITY: follow the artifacts on the floor plan — furniture, appliances, fixtures. Place them EXACTLY as shown on the plan. Logically understand what is depicted and generate only semantically relevant artifacts for this room type.
- Client preferences are OVERLAID on top of the plan artifacts: style, colors, materials — this is the interior styling layer over the layout.
- Where the plan is EMPTY — leave it empty! Do not fill free space with extra furniture or decor.
- PRESERVE the room GEOMETRY and furniture PROPORTIONS from the plan — do not distort sizes or shapes.
- Camera: TOP-DOWN VIEW (bird's eye view), camera directly above the room looking straight down.
- Minimalism, clean surfaces, no extra decor.
- Doorways on the plan are shown as gaps in the perimeter with an arc (like letter "D"). In the generated image all doors must be FULLY CLOSED — appear as solid wall with door panel matching wall color, no visible gaps, no views into other rooms.
- Photorealism, professional interior magazine photography quality.
- No text, labels, or watermarks on the image.`;

const answers = typeof data.answers === 'string' ? JSON.parse(data.answers) : data.answers;

// Функция обработки одной комнаты
async function processRoom(i, room) {
    const roomName = room.name || 'unknown';
    const safeName = roomName.replace(/ /g, '_').replace(/\//g, '-');

    try {
        // Скачиваем кроп из S3
        const cropKey = 'fsk-generate-image/' + data.task_id + '/L1_crops/' + (i + 1) + '_' + safeName + '_crop.png';
        const cropResp = await s3.send(new GetObjectCommand({ Bucket: 'fsk-service', Key: cropKey }));
        const cropBytes = await cropResp.Body.transformToByteArray();
        const cropBase64 = Buffer.from(cropBytes).toString('base64');

        // Собираем предпочтения из опросника
        const prefLines = [];
        if (answers.style) prefLines.push('- Interior style: ' + answers.style);
        if (answers.colors) prefLines.push('- Color palette: ' + answers.colors);
        if (answers.materials) prefLines.push('- Materials: ' + (Array.isArray(answers.materials) ? answers.materials.join(', ') : answers.materials));
        const prefsBlock = prefLines.length > 0 ? prefLines.join('\n') : '- Default modern style';

        const userPrompt = `Room: ${roomName}, area ${room.area} sq.m, shape: ${room.shape}.

Room analysis (from floor plan):
${room.analysis || 'No analysis available'}

STRICTLY follow these dimensions and proportions!

Client preferences:
${prefsBlock}`;

        const content = [
            { type: "text", text: SYSTEM_PROMPT + '\n\n' + userPrompt },
            { type: "image_url", image_url: { url: "data:image/png;base64," + cropBase64 } }
        ];

        // Вызов Gemini Image
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

        // Извлекаем изображение из ответа
        const message = response.data.choices[0].message;
        let imgBase64 = null;
        if (message.images && message.images.length > 0) {
            const url = message.images[0].image_url.url;
            imgBase64 = url.includes('base64,') ? url.split('base64,')[1] : url;
        } else if (message.content && message.content.includes('base64,')) {
            imgBase64 = message.content.split('base64,')[1].split(')')[0];
        }

        if (!imgBase64) return { name: roomName, error: 'no image' };

        // Сохраняем референс в S3
        const refKey = 'fsk-generate-image/' + data.task_id + '/L2_references/' + safeName + '.png';
        await s3.send(new PutObjectCommand({
            Bucket: 'fsk-service', Key: refKey,
            Body: Buffer.from(imgBase64, 'base64'), ContentType: 'image/png'
        }));

        return { name: roomName, s3_key: refKey };
    } catch(e) {
        return { name: roomName, error: String(e).substring(0, 200) };
    }
}

// Запускаем все комнаты ПАРАЛЛЕЛЬНО
const promises = data.analysis.rooms.map((room, i) => processRoom(i, room));
const savedRefs = await Promise.all(promises);

return {
    task_id: data.task_id,
    references: savedRefs
};
