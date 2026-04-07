// Слой 4, Нода 1: Stitch + Refine — общий рендер квартиры сверху
// Вход: $input = task_id (строка)
// Шаги:
//   1. Загружаем analysis из S3 + listим L2_references
//   2. Stitch через Python /stitch (склейка по полигонам, без AI)
//   3. Скачиваем stitched + schema_x2 из S3
//   4. Gemini Image dual (refine — доработка стен/проходов по схеме)
//   5. Сохраняем composite.png в S3
// Выход: {task_id, stitched_key, composite_key}
// Статус: ПРОТЕСТИРОВАНО ✅ (stitched ~3.2MB + composite ~1.2MB)

const axios = require('axios');
const { S3Client, GetObjectCommand, PutObjectCommand, ListObjectsV2Command } = require('@aws-sdk/client-s3');

const taskId = $input.trim();

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

const REFINE_PROMPT = `Ты получаешь ДВА изображения:

ИЗОБРАЖЕНИЕ 1 — СКЛЕЕННЫЙ РЕФЕРЕНС квартиры сверху. Это фотореалистичные интерьеры комнат, вставленные по координатам схемы. Геометрия и расположение комнат УЖЕ ПРАВИЛЬНОЕ. Но есть проблемы: стыки между комнатами грубые, дверные проёмы не проработаны, стены между комнатами неаккуратные.

ИЗОБРАЖЕНИЕ 2 — ОРИГИНАЛЬНАЯ ЧЁРНО-БЕЛАЯ СХЕМА ПЛАНИРОВКИ (апскейл). На ней точно видны: стены, дверные проёмы (дуги), окна (параллельные линии), границы комнат.

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

// === 1. Загружаем analysis ===
const analysisResp = await s3.send(new GetObjectCommand({
    Bucket: 'fsk-service',
    Key: 'fsk-generate-image/' + taskId + '/L1_crops/analysis.json'
}));
const analysisBody = await analysisResp.Body.transformToString();
const analysis = JSON.parse(analysisBody);

// === 2. Листим референсы ===
const listResp = await s3.send(new ListObjectsV2Command({
    Bucket: 'fsk-service',
    Prefix: 'fsk-generate-image/' + taskId + '/L2_references/'
}));

const refsByName = {};
if (listResp.Contents) {
    for (const obj of listResp.Contents) {
        const fname = obj.Key.split('/').pop();
        const safeName = fname.replace(/\.png$/, '');
        refsByName[safeName] = obj.Key;
    }
}

// === 3. Собираем rooms для /stitch (только те, у кого есть референс) ===
const stitchRooms = [];
for (const room of analysis.rooms) {
    const roomName = room.name || 'unknown';
    const safeName = roomName.replace(/ /g, '_').replace(/\//g, '-');
    const refKey = refsByName[safeName];
    if (!refKey) continue;
    if (!room.polygon || room.polygon.length < 3) continue;
    stitchRooms.push({
        name: roomName,
        polygon: room.polygon,
        ref_s3_key: refKey
    });
}

// === 4. Stitch через Python API ===
const schemaKey = 'fsk-generate-image/' + taskId + '/L1_crops/schema_x2.png';
const stitchResp = await axios.post('https://llm-home.fsk.fvds.ru/stitch', {
    task_id: taskId,
    schema_s3_key: schemaKey,
    rooms: stitchRooms
}, { timeout: 120000 });

const stitchedKey = stitchResp.data.stitched_key;

// === 5. Скачиваем stitched + schema из S3 ===
const stitchedObj = await s3.send(new GetObjectCommand({ Bucket: 'fsk-service', Key: stitchedKey }));
const stitchedBytes = await stitchedObj.Body.transformToByteArray();
const stitchedBase64 = Buffer.from(stitchedBytes).toString('base64');

const schemaObj = await s3.send(new GetObjectCommand({ Bucket: 'fsk-service', Key: schemaKey }));
const schemaBytes = await schemaObj.Body.transformToByteArray();
const schemaBase64 = Buffer.from(schemaBytes).toString('base64');

// === 6. Gemini Image dual (stitched + schema) → refined composite ===
const content = [
    { type: "text", text: REFINE_PROMPT },
    { type: "image_url", image_url: { url: "data:image/png;base64," + stitchedBase64 } },
    { type: "image_url", image_url: { url: "data:image/png;base64," + schemaBase64 } }
];

const response = await axios.post("https://openrouter.ai/api/v1/chat/completions", {
    model: "google/gemini-3.1-flash-image-preview",
    messages: [{ role: "user", content: content }],
    temperature: 1
}, {
    headers: {
        "Authorization": "Bearer <OPENROUTER_API_KEY>",
        "Content-Type": "application/json"
    },
    timeout: 180000
});

const message = response.data.choices[0].message;
let imgBase64 = null;
if (message.images && message.images.length > 0) {
    const url = message.images[0].image_url.url;
    imgBase64 = url.includes('base64,') ? url.split('base64,')[1] : url;
} else if (message.content && message.content.includes('base64,')) {
    imgBase64 = message.content.split('base64,')[1].split(')')[0];
}

if (!imgBase64) {
    return { task_id: taskId, stitched_key: stitchedKey, error: 'no composite from gemini' };
}

// === 7. Сохраняем composite.png в S3 ===
const compositeKey = 'fsk-generate-image/' + taskId + '/L4_composite/composite.png';
await s3.send(new PutObjectCommand({
    Bucket: 'fsk-service',
    Key: compositeKey,
    Body: Buffer.from(imgBase64, 'base64'),
    ContentType: 'image/png'
}));

return {
    task_id: taskId,
    stitched_key: stitchedKey,
    composite_key: compositeKey,
    rooms_stitched: stitchRooms.length
};
