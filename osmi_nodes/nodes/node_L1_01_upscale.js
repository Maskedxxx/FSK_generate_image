// Слой 1, Нода 1: Приём изображения + опросника → апскейл через Python API → S3
// Вход: $input = "base64_изображения|||json_опросника"
// API: https://llm-home.fsk.fvds.ru/upscale (с task_id → сохраняет в S3, без base64 в ответе)
// Output Variable: upscale_result
// Выход: {task_id, s3_key, original_size, new_size, answers} — БЕЗ base64

const axios = require('axios');

// Разделяем вход на base64 схемы и JSON опросника
const parts = $input.split('|||');
const imageBase64 = parts[0] || "";
const answersJson = parts[1] || "{}";

// Генерируем task_id (раньше был в ноде 2, перенесли сюда чтобы /upscale сразу сохранял в S3)
const now = new Date();
const date = now.toISOString().split('T')[0];
const rand = Math.random().toString(36).substring(2, 10);
const taskId = date + '_' + rand;

// Апскейл схемы x4 через Python API — с task_id, результат сразу в S3
const response = await axios.post('https://llm-home.fsk.fvds.ru/upscale', {
    image_base64: imageBase64,
    task_id: taskId,
    zoom_factor: 4,
    max_side: 4000
}, { timeout: 60000 });

const result = response.data;

return JSON.stringify({
    task_id: taskId,
    s3_key: result.s3_key,
    original_size: result.original_size,
    new_size: result.new_size,
    answers: answersJson
});
