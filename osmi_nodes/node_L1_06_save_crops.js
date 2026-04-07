// Слой 1, Нода 6: Сохранение кропов в S3
// Вход: $crop_result (объект от ноды 5)
// Output Variable: crops_saved
// Статус: ПРОТЕСТИРОВАНО ✅

const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');

const data = $crop_result;

const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});

const savedCrops = [];

for (let i = 0; i < data.crops.length; i++) {
    const crop = data.crops[i];
    const safeName = crop.name.replace(/ /g, '_').replace(/\//g, '-');
    const key = 'fsk-generate-image/' + data.task_id + '/L1_crops/' + (i + 1) + '_' + safeName + '_crop.png';

    const imageBuffer = Buffer.from(crop.image_base64, 'base64');

    await s3.send(new PutObjectCommand({
        Bucket: 'fsk-service',
        Key: key,
        Body: imageBuffer,
        ContentType: 'image/png'
    }));

    savedCrops.push({
        name: crop.name,
        s3_key: key,
        size: crop.size
    });
}

return {
    task_id: data.task_id,
    answers: data.answers,
    analysis: data.analysis,
    crops: savedCrops
};
