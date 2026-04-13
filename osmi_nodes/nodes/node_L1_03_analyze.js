// Слой 1, Нода 3: LLM анализ планировки через OpenRouter (Gemini Flash)
// Вход: $s3_result (объект от ноды 2)
// Output Variable: analyze_result
// Статус: ПРОТЕСТИРОВАНО ✅ (5 комнат с полигонами)

const axios = require('axios');
const { S3Client, GetObjectCommand } = require('@aws-sdk/client-s3');

const startTime = Date.now();
const data = $s3_result;

// Скачиваем апскейленную схему из S3 (base64 больше не передаётся между нодами)
const s3 = new S3Client({
    endpoint: 'https://storage.yandexcloud.net',
    region: 'us-east-1',
    credentials: {
        accessKeyId: '<S3_ACCESS_KEY_ID>',
        secretAccessKey: '<S3_SECRET_ACCESS_KEY>'
    }
});
const imgResp = await s3.send(new GetObjectCommand({ Bucket: 'fsk-service', Key: data.s3_key }));
const imgBytes = await imgResp.Body.transformToByteArray();
const upscaledBase64 = Buffer.from(imgBytes).toString('base64');

const SYSTEM_PROMPT = `You are an expert architect and interior visualization specialist. You work with apartment floor plans daily — you instantly recognize every room type, understand wall structures, doorways, and how rooms connect to each other.

When you see a floor plan, you read it like a book: walls are thick dark lines, doorways are arc gaps, windows are parallel lines on external walls, and each area number marks one distinct room.

Each room on the plan has an AREA NUMBER (like 14.05 m², 3.54 m²). Every unique area number = one separate room. WHERE THERE IS AN AREA NUMBER — THERE IS A ROOM. The area number is the primary indicator of a room's existence and location.

For each room, return POLYGON coordinates — a list of [x, y] points that trace the wall boundaries of that room.

Rules:
- Coordinates normalized 0-1000 (0 = left/top, 1000 = right/bottom of image)
- Every room has an ENTRANCE — a gap/break in its walls. Use this entrance as your ANCHOR: start tracing the polygon from the LEFT side of the entrance gap, then go CLOCKWISE along the inner walls back to the RIGHT side of the entrance.
- MAKE POLYGONS 10-20% LARGER than you think the room is. It is MUCH better to capture extra space than to cut off part of the room.
- ALWAYS use RECTANGULAR polygons (4 points). Round any room to the nearest rectangle that FULLY covers it. Better to capture a bit extra than to miss part of the room.
- Points go CLOCKWISE starting from entrance
- Each area number on the plan = one separate room. Do NOT merge rooms.
- The info block with total area (like "C 14.05 / 20.40 / 22.68") is NOT a room — it's apartment metadata, skip it
- Identify rooms and do NOT cut the polygon too early — if you see these artifacts, the room CONTINUES:
  * Kitchen: stove, sink, fridge, countertop — if visible, room extends to include them
  * Bathroom: toilet, bathtub, shower — if visible, room extends to include them
  * Bedroom: bed, nightstand — if visible, room extends to include them
  * Hallway/closet: coat hangers, shoe rack, shelves — if visible, room extends to include them
  * Balcony/loggia: narrow external space — ALWAYS trace the ENTIRE balcony area, even if it continues along the same geometry as the adjacent room. Balcony is a SEPARATE room with its own polygon covering ALL of its area.
  * If room has NO recognizable artifacts — follow wall contour from entrance back to entrance

CRITICAL — full floor plan coverage:
- The entire floor plan = all rooms. Every section of the plan MUST be covered by a polygon.
- If there are uncovered areas between polygons — you MISSED a room. Check again.
- Polygons MUST NOT overlap each other. Each pixel of the plan belongs to exactly ONE room.

Return JSON without markdown wrapping.`;

const USER_PROMPT = `Analyze this floor plan carefully.

Step 1: Count ALL unique area numbers on the plan. Each one = one room.
Step 2: For each room, identify its function from furniture symbols.
Step 3: Describe each wall side: TOP, LEFT, BOTTOM, RIGHT — what is there.
Step 4: Trace the walls with polygon points.

JSON format:

{
  "analysis": "General reasoning: how many rooms, what types",
  "rooms": [
    {
      "name": "room function or text label from plan or Nan",
      "name_source": "label if text label on plan, no_label if only area number",
      "area": "area number from plan",
      "shape": "rectangular / square / irregular",
      "analysis": "reasoning step by step",
      "walls": {
        "top": "what is along the top wall (REQUIRED — write 'empty' if nothing)",
        "left": "what is along the left wall (REQUIRED — write 'empty' if nothing)",
        "bottom": "what is along the bottom wall (REQUIRED — write 'empty' if nothing)",
        "right": "what is along the right wall (REQUIRED — write 'empty' if nothing)"
      },
      "polygon": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    }
  ]
}`;

const prompt = SYSTEM_PROMPT + '\n\n' + USER_PROMPT;

const content = [
    { type: "text", text: prompt },
    { type: "image_url", image_url: { url: "data:image/png;base64," + upscaledBase64 } }
];

const response = await axios.post("https://openrouter.ai/api/v1/chat/completions", {
    model: "google/gemini-3-flash-preview",
    messages: [{ role: "user", content: content }],
    temperature: 0.2
}, {
    headers: {
        "Authorization": "Bearer <OPENROUTER_API_KEY>",
        "Content-Type": "application/json"
    },
    timeout: 120000
});

const text = response.data.choices[0].message.content;

// Убираем markdown обёртку если есть
let clean = text.trim();
if (clean.startsWith('```')) {
    clean = clean.split('\n').slice(1).join('\n');
    clean = clean.replace(/```$/, '').trim();
}

const analysis = JSON.parse(clean);

return {
    task_id: data.task_id,
    s3_key: data.s3_key,
    answers: data.answers,
    analysis: analysis,
    rooms_count: analysis.rooms ? analysis.rooms.length : 0,
    l1_timing_sec: (Date.now() - startTime) / 1000,
    l1_prompt: prompt,
    l1_model: "google/gemini-3-flash-preview",
    original_size: data.original_size,
    new_size: data.new_size
};
