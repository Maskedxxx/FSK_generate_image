// Слой 1, Нода 4: Сохранение analysis.json + L1_meta.json + schema_with_polygons.png
// Вход: $analyze_result (объект от ноды 3)
// Статус: ПРОТЕСТИРОВАНО ✅

const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');
const axios = require('axios');

const data = $analyze_result;

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

// 1. Сохраняем analysis.json
const analysisKey = 'fsk-generate-image/' + data.task_id + '/L1_crops/analysis.json';
await s3.send(new PutObjectCommand({
    Bucket: 'fsk-service',
    Key: analysisKey,
    Body: JSON.stringify(data.analysis, null, 2),
    ContentType: 'application/json'
}));

// 2. Сохраняем L1_meta.json (модель, тайминги, размеры, промпт)
const meta = {
    layer: 1,
    model: data.l1_model || 'google/gemini-3-flash-preview',
    timestamp: new Date().toISOString(),
    input: {
        original_size: data.original_size || [],
        zoomed_size: data.new_size || [],
        zoom_factor: 4,
        max_side_px: 4000
    },
    output: {
        rooms_count: data.rooms_count || 0
    },
    timing: {
        osmi_call_sec: data.l1_timing_sec || 0
    },
    prompt: data.l1_prompt || ''
};
const metaKey = 'fsk-generate-image/' + data.task_id + '/L1_crops/L1_meta.json';
await s3.send(new PutObjectCommand({
    Bucket: 'fsk-service',
    Key: metaKey,
    Body: JSON.stringify(meta, null, 2),
    ContentType: 'application/json'
}));

// 3. Сохраняем schema_with_polygons.png через Python API (визуализация полигонов)
const rooms = data.analysis.rooms.map(r => ({
    name: r.name || 'unknown',
    polygon: r.polygon || []
}));

await axios.post('https://llm-home.fsk.fvds.ru/draw_polygons', {
    s3_key: 'fsk-generate-image/' + data.task_id + '/L1_crops/schema_x2.png',
    task_id: data.task_id,
    rooms: rooms
}, { timeout: 60000 });

return {
    status: 'ok',
    task_id: data.task_id,
    analysis_key: analysisKey,
    meta_key: metaKey,
    rooms_count: data.rooms_count
};
