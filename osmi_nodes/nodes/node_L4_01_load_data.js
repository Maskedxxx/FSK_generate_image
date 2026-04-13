// Слой 4, Нода 1: Загрузка данных для stitch
// Вход: $input = task_id (строка)
// Output Variable: l4_data (в ноде Set Variable: {{customFunction_0.data.instance}})

const { S3Client, GetObjectCommand, ListObjectsV2Command } = require('@aws-sdk/client-s3');

const taskId = $input.trim();

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

// Скачиваем analysis
const analysisResp = await s3.send(new GetObjectCommand({
    Bucket: 'fsk-service',
    Key: 'fsk-generate-image/' + taskId + '/L1_crops/analysis.json'
}));
const analysis = JSON.parse(await analysisResp.Body.transformToString());

// Список референсов
const listResp = await s3.send(new ListObjectsV2Command({
    Bucket: 'fsk-service',
    Prefix: 'fsk-generate-image/' + taskId + '/L2_references/'
}));
const refKeys = (listResp.Contents || []).map(o => o.Key).filter(k => k.endsWith('.png'));

// Собираем rooms для /stitch
const rooms = analysis.rooms.map(r => {
    const safeName = (r.name || 'unknown').replace(/ /g, '_').replace(/\//g, '-');
    const refKey = refKeys.find(k => k.includes(safeName + '.png'));
    return {
        name: r.name,
        polygon: r.polygon || [],
        ref_s3_key: refKey || ''
    };
}).filter(r => r.ref_s3_key && r.polygon.length >= 3);

return {
    task_id: taskId,
    rooms: rooms
};
