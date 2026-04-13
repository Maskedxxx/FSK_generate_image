// Слой 2 Нода 1: Загрузка данных из S3 по task_id
// Вход: $input = task_id (строка)
// Output Variable: l2_data

const { S3Client, GetObjectCommand } = require('@aws-sdk/client-s3');

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
const analysisBody = await analysisResp.Body.transformToString();
const analysis = JSON.parse(analysisBody);

// Скачиваем meta.json (опросник)
const metaResp = await s3.send(new GetObjectCommand({
    Bucket: 'fsk-service',
    Key: 'fsk-generate-image/' + taskId + '/meta.json'
}));
const metaBody = await metaResp.Body.transformToString();
const meta = JSON.parse(metaBody);
const answers = meta.answers || {};

return {
    task_id: taskId,
    analysis: analysis,
    answers: answers,
    rooms_count: analysis.rooms ? analysis.rooms.length : 0
};
