// Слой 1, Нода 5: Кроп комнат по полигонам через Python API (по одной в цикле)
// Вход: $analyze_result (объект от ноды 3)
// Output Variable: crop_result
// ИНСАЙТ: цикл по одной комнате — иначе ответ с 5 base64 (~3MB) рвёт тунель
// Статус: ПРОТЕСТИРОВАНО ✅

const axios = require('axios');

const data = $analyze_result;
const s3Key = 'fsk-generate-image/' + data.task_id + '/L1_crops/schema_x2.png';
const allCrops = [];

// Кропаем каждую комнату отдельным вызовом
for (let i = 0; i < data.analysis.rooms.length; i++) {
    const room = data.analysis.rooms[i];

    const response = await axios.post('https://llm-home.fsk.fvds.ru/crop', {
        s3_key: s3Key,
        rooms: [{ name: room.name || 'unknown', polygon: room.polygon || [] }]
    }, { timeout: 60000 });

    if (response.data.crops && response.data.crops.length > 0) {
        allCrops.push(response.data.crops[0]);
    }
}

return {
    task_id: data.task_id,
    answers: data.answers,
    analysis: data.analysis,
    crops: allCrops
};
