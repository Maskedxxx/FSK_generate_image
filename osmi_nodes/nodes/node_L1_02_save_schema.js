// Слой 1, Нода 2: Сохранение meta.json в S3
// Вход: $upscale_result (объект от ноды 1: {task_id, s3_key, original_size, new_size, answers})
// schema_x2.png уже сохранена Python-сервисом /upscale — здесь только meta.json
// Output Variable: s3_result

const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');

const data = $upscale_result;
const taskId = data.task_id;

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

// Сохраняем meta.json с опросником
const meta = {
    created_at: new Date().toISOString(),
    type: 'pipeline',
    answers: JSON.parse(data.answers)
};
const metaKey = 'fsk-generate-image/' + taskId + '/meta.json';

await s3.send(new PutObjectCommand({
    Bucket: 'fsk-service',
    Key: metaKey,
    Body: JSON.stringify(meta, null, 2),
    ContentType: 'application/json'
}));

return {
    status: 'ok',
    task_id: taskId,
    s3_key: data.s3_key,
    original_size: data.original_size,
    new_size: data.new_size,
    answers: data.answers
};
