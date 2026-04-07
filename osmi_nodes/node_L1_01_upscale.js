// Слой 1, Нода 1: Приём изображения + опросника → апскейл через Python API
// Вход: $input = "base64_изображения|||json_опросника"
// API: https://llm-home.fsk.fvds.ru/upscale
// Output Variable: upscale_result
// Статус: ПРОТЕСТИРОВАНО ✅

const axios = require('axios');

// Разделяем вход на base64 схемы и JSON опросника
const parts = $input.split('|||');
const imageBase64 = parts[0] || "";
const answersJson = parts[1] || "{}";

// Апскейл схемы x4 через Python API
const response = await axios.post('https://llm-home.fsk.fvds.ru/upscale', {
    image_base64: imageBase64,
    zoom_factor: 4,
    max_side: 4000
});

const result = response.data;

return {
    upscaled_base64: result.image_base64,
    original_size: result.original_size,
    new_size: result.new_size,
    answers: answersJson
};
