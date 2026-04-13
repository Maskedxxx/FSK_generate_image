// Слой 1, Нода 5: Кроп комнат по полигонам (ПАРАЛЛЕЛЬНО через Promise.all)
// Вход: $analyze_result (объект от ноды 3)
// Output Variable: crop_result

const axios = require('axios');

const data = $analyze_result;
const s3Key = 'fsk-generate-image/' + data.task_id + '/L1_crops/schema_x2.png';

// Все кропы ПАРАЛЛЕЛЬНО — они независимы друг от друга
const promises = data.analysis.rooms.map((room, i) => {
    return axios.post('https://llm-home.fsk.fvds.ru/crop', {
        s3_key: s3Key,
        rooms: [{ name: room.name || 'unknown', polygon: room.polygon || [] }]
    }, { timeout: 60000 }).then(response => {
        if (response.data.crops && response.data.crops.length > 0) {
            return response.data.crops[0];
        }
        return null;
    }).catch(e => {
        return { name: room.name || 'unknown', error: String(e).substring(0, 200) };
    });
});

const results = await Promise.all(promises);
const allCrops = results.filter(c => c && !c.error);

return {
    task_id: data.task_id,
    answers: data.answers,
    analysis: data.analysis,
    crops: allCrops
};
