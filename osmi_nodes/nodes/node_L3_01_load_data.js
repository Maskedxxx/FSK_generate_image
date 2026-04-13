// Слой 3, Нода 1: Загрузка данных + список референсов из S3
// Вход: $input = task_id (строка)
// Output Variable: l3_data

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

// Скачиваем analysis.json
const analysisResp = await s3.send(new GetObjectCommand({
    Bucket: 'fsk-service',
    Key: 'fsk-generate-image/' + taskId + '/L1_crops/analysis.json'
}));
const analysis = JSON.parse(await analysisResp.Body.transformToString());

// Список референсов в S3
const listResp = await s3.send(new ListObjectsV2Command({
    Bucket: 'fsk-service',
    Prefix: 'fsk-generate-image/' + taskId + '/L2_references/'
}));
const refKeys = (listResp.Contents || [])
    .map(obj => obj.Key)
    .filter(k => k.endsWith('.png'));

return {
    task_id: taskId,
    analysis: analysis,
    ref_keys: refKeys,
    rooms_count: analysis.rooms ? analysis.rooms.length : 0
};
