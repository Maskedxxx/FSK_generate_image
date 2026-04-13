// Слой 4, Нода 2: Stitch + Refine — финальный composite квартиры сверху
// Вход: $l4_data (объект от ноды 1 через Set Variable)
// ЗАВЕРШАЮЩАЯ нода флоу

const axios = require('axios');
const { S3Client, GetObjectCommand, PutObjectCommand } = require('@aws-sdk/client-s3');

const data = $l4_data;
const taskId = data.task_id;

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

// 1. Stitch через Python API
const stitchResp = await axios.post('https://llm-home.fsk.fvds.ru/stitch', {
    task_id: taskId,
    schema_s3_key: 'fsk-generate-image/' + taskId + '/L1_crops/schema_x2.png',
    rooms: data.rooms
}, { timeout: 120000 });

const stitchedKey = stitchResp.data.stitched_key;

// 2. Скачиваем stitched + schema из S3
const stitchedResp = await s3.send(new GetObjectCommand({ Bucket: 'fsk-service', Key: stitchedKey }));
const stitchedB64 = Buffer.from(await stitchedResp.Body.transformToByteArray()).toString('base64');

const schemaResp = await s3.send(new GetObjectCommand({
    Bucket: 'fsk-service', Key: 'fsk-generate-image/' + taskId + '/L1_crops/schema_x2.png'
}));
const schemaB64 = Buffer.from(await schemaResp.Body.transformToByteArray()).toString('base64');

// 3. Refine через Gemini Image dual
const REFINE_PROMPT = `Ты получаешь ДВА изображения:

ИЗОБРАЖЕНИЕ 1 — СКЛЕЕННЫЙ РЕФЕРЕНС квартиры сверху. Это фотореалистичные интерьеры комнат, вставленные по координатам схемы. Геометрия и расположение
комнат УЖЕ ПРАВИЛЬНОЕ. Но есть проблемы: стыки между комнатами грубые, дверные проёмы не проработаны, стены между комнатами неаккуратные.

ИЗОБРАЖЕНИЕ 2 — ОРИГИНАЛЬНАЯ ЧЁРНО-БЕЛАЯ СХЕМА ПЛАНИРОВКИ (апскейл). На ней точно видны: стены, дверные проёмы (дуги), окна (параллельные линии),
границы комнат.

Твоя задача — ДОРАБОТАТЬ склеенный референс (изображение 1) используя схему (изображение 2) как чертёж:

Step by step:
1. Сравни склеенный референс со схемой — найди где стены, проходы, двери
2. ДВЕРНЫЕ ПРОЁМЫ: на схеме двери показаны дугами — в референсе сделай аккуратные проходы между комнатами в этих местах
3. СТЕНЫ: сделай чёткие белые стены между комнатами точно как на схеме
4. СТЫКИ: сгладь грубые стыки между комнатами, сделай переходы естественными
5. ОКНА: проверь что окна на своих местах (внешние стены на схеме)
6. НЕ МЕНЯЙ интерьер комнат — мебель, материалы, цвета оставь как есть
7. НЕ МЕНЯЙ геометрию — расположение и размеры комнат уже правильные
8. Вид строго сверху, ортографическая проекция
9. Высокое разрешение, фотореализм
10. Без текста, надписей, водяных знаков`;

const refineResp = await axios.post("https://openrouter.ai/api/v1/chat/completions", {
    model: "google/gemini-3.1-flash-image-preview",
    messages: [{ role: "user", content: [
        { type: "text", text: REFINE_PROMPT },
        { type: "image_url", image_url: { url: "data:image/png;base64," + stitchedB64 } },
        { type: "image_url", image_url: { url: "data:image/png;base64," + schemaB64 } }
    ]}],
    temperature: 1
}, {
    headers: {
        "Authorization": "Bearer <OPENROUTER_API_KEY>",
        "Content-Type": "application/json"
    },
    timeout: 180000
});

// Извлекаем изображение
const msg = refineResp.data.choices[0].message;
let compositeB64 = null;
if (msg.images && msg.images.length > 0) {
    const url = msg.images[0].image_url.url;
    compositeB64 = url.includes('base64,') ? url.split('base64,')[1] : url;
} else if (msg.content && msg.content.includes('base64,')) {
    compositeB64 = msg.content.split('base64,')[1].split(')')[0];
}

let compositeKey = '';
if (compositeB64) {
    compositeKey = 'fsk-generate-image/' + taskId + '/L4_composite/composite.png';
    await s3.send(new PutObjectCommand({
        Bucket: 'fsk-service', Key: compositeKey,
        Body: Buffer.from(compositeB64, 'base64'), ContentType: 'image/png'
    }));
}

return JSON.stringify({
    task_id: taskId,
    stitched_key: stitchedKey,
    composite_key: compositeKey,
    status: compositeB64 ? 'ok' : 'no image from refine'
});
