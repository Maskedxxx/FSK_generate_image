// Слой 3, Нода 1: Загрузка данных + список референсов из S3
// Вход: $input = task_id (строка)
// Output Variable: l3_data
// Выход: {task_id, analysis, refs[{name, s3_key}], rooms_count}
// Статус: ПРОТЕСТИРОВАНО ✅

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

// 1. Скачиваем analysis.json
const analysisResp = await s3.send(new GetObjectCommand({
    Bucket: 'fsk-service',
    Key: 'fsk-generate-image/' + taskId + '/L1_crops/analysis.json'
}));
const analysisBody = await analysisResp.Body.transformToString();
const analysis = JSON.parse(analysisBody);

// 2. Листим L2_references — получаем s3_key каждого референса
const listResp = await s3.send(new ListObjectsV2Command({
    Bucket: 'fsk-service',
    Prefix: 'fsk-generate-image/' + taskId + '/L2_references/'
}));

const refsByName = {};
if (listResp.Contents) {
    for (const obj of listResp.Contents) {
        // ключ: fsk-generate-image/<task>/L2_references/<safe_name>.png
        const fname = obj.Key.split('/').pop();      // safe_name.png
        const safeName = fname.replace(/\.png$/, ''); // safe_name
        refsByName[safeName] = obj.Key;
    }
}

// 3. Сопоставляем комнаты из analysis с найденными референсами по safe_name
const refs = analysis.rooms.map(room => {
    const roomName = room.name || 'unknown';
    const safeName = roomName.replace(/ /g, '_').replace(/\//g, '-');
    return {
        name: roomName,
        safe_name: safeName,
        s3_key: refsByName[safeName] || null
    };
});

return {
    task_id: taskId,
    analysis: analysis,
    refs: refs,
    rooms_count: analysis.rooms ? analysis.rooms.length : 0
};
