// Слой 1, Нода 2: Генерация task_id + сохранение schema_x2.png и meta.json в S3
// Вход: $upscale_result (объект от ноды 1)
// Output Variable: s3_result
// Статус: ПРОТЕСТИРОВАНО ✅

const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');

const data = $upscale_result;

// Генерируем task_id (дата + random)
const now = new Date();
const date = now.toISOString().split('T')[0];
const rand = Math.random().toString(36).substring(2, 10);
const taskId = date + '_' + rand;

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

// 1. Сохраняем апскейленную схему
const imageBuffer = Buffer.from(data.upscaled_base64, 'base64');
const schemaKey = 'fsk-generate-image/' + taskId + '/L1_crops/schema_x2.png';

await s3.send(new PutObjectCommand({
    Bucket: 'fsk-service',
    Key: schemaKey,
    Body: imageBuffer,
    ContentType: 'image/png'
}));

// 2. Сохраняем meta.json с опросником
const meta = {
    created_at: now.toISOString(),
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
    s3_key: schemaKey,
    original_size: data.original_size,
    new_size: data.new_size,
    answers: data.answers,
    upscaled_base64: data.upscaled_base64
};
