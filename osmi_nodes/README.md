# OSMI ноды — миграция пайплайна

Полный пайплайн FSK Generate Image, перенесённый с Python FastAPI на платформу
**OSMI** (форк Flowise 4.2.1, Agent Flow V2).

## Архитектура

```
                    ┌─────────────────────────────────────┐
                    │            OSMI Agent Flow          │
                    │   (LLM ноды + Custom Function JS)   │
                    └──────────────┬──────────────────────┘
                                   │
                ┌──────────────────┼──────────────────────┐
                │                  │                      │
                ▼                  ▼                      ▼
        ┌───────────────┐  ┌───────────────┐    ┌──────────────────┐
        │  OpenRouter   │  │   S3 (Yandex) │    │  Python Image    │
        │  Gemini 3 / 3.1│ │  fsk-service  │    │     Service      │
        └───────────────┘  └───────────────┘    └──────────────────┘
                                                  /upscale /crop
                                                  /draw_polygons
                                                  /rotate /stitch
```

### Доступно в OSMI Custom Function:
- `axios`, `node-fetch` — HTTP
- `@aws-sdk/client-s3` — Yandex Object Storage
- `fs`, `buffer` — файлы

### НЕ доступно:
- `sharp`, `jimp`, `canvas`, `pngjs` — обработка пикселей
- `$flow.state` — глобальное состояние
- `process.version` и др. nodejs-утилиты

### Вывод:
Все операции с пикселями (апскейл, кроп, поворот, склейка) — через HTTP-вызов
Python-микросервиса `image_service.py`.

---

## Слой 1: Анализ планировки (NEMOV_FSK_СЛОЙ_1)

Принимает base64 схемы + JSON опросника, выдаёт `analysis.json` с полигонами комнат.

| # | Файл | Назначение | Output Var |
|---|------|------------|------------|
| 1 | `node_L1_01_upscale.js` | Парсит вход (base64 \|\|\| answers) → /upscale x4 | `upscale_result` |
| 2 | `node_L1_02_save_schema.js` | Генерит task_id, сохраняет schema_x2.png + meta.json в S3 | `s3_result` |
| 3 | `node_L1_03_analyze.js` | LLM-анализ Gemini 3 Flash → JSON с полигонами | `analyze_result` |
| 4 | `node_L1_04_save_analysis.js` | Сохраняет analysis.json + L1_meta.json + schema_with_polygons.png | — |
| 5 | `node_L1_05_crop.js` | Кроп комнат через /crop (по одной — иначе тунель рвёт) | `crop_result` |
| 6 | `node_L1_06_save_crops.js` | Заливает кропы в L1_crops/ | `crops_saved` |

**Артефакты в S3:** `fsk-generate-image/{task_id}/L1_crops/`
- `schema_x2.png`, `analysis.json`, `L1_meta.json`, `schema_with_polygons.png`
- `1_<room>_crop.png` … `N_<room>_crop.png`
- `meta.json` (на уровне `{task_id}/`) — answers + created_at

---

## Слой 2: Генерация референсов сверху (NEMOV_FSK_СЛОЙ_2)

API: `https://app.osmi-ai.ru/api/v1/prediction/332dcec8-2a8c-480e-98ec-be06afb9322c`
Вход: `task_id` (строка)

| # | Файл | Назначение | Output Var |
|---|------|------------|------------|
| 1 | `node_L2_01_load_data.js` | Скачивает analysis.json + meta.json по task_id | `l2_data` |
| 2 | `node_L2_02_generate_refs.js` | **Promise.all** по комнатам → Gemini 3.1 Image → референс в S3 | — |

**Артефакты:** `fsk-generate-image/{task_id}/L2_references/<room>.png` (5 файлов)

**Инсайт:** последовательная обработка 5 комнат = ~2.5 мин → таймаут nginx 240 сек.
`Promise.all` сократил до ~30 сек.

---

## Слой 3: Рендер с двух сторон (NEMOV_FSK_СЛОЙ_3)

API: `https://app.osmi-ai.ru/api/v1/prediction/0907264d-b0a3-4570-a8e5-41b083d311fb`
Вход: `task_id` (строка)

| # | Файл | Назначение | Output Var |
|---|------|------------|------------|
| 1 | `node_L3_01_load_data.js` | analysis + список L2_references из S3 | `l3_data` |
| 2 | `node_L3_02_render_sides.js` | Параллельно (5 × 2): /rotate → Gemini Image → side_a/b в S3 | — |

**Артефакты:** `fsk-generate-image/{task_id}/L3_renders/` — 20 файлов:
- `<room>_prepared_<angle>deg.png` × 10 (от Python /rotate)
- `<room>_side_a.png` + `<room>_side_b.png` × 10 (от Gemini Image)

**Инсайт:** рендерим **все 10 рендеров параллельно** (5 комнат × 2 стороны через
`Promise.all`). Использует параметр `side: "a"|"b"` в `/rotate` — Python сам определяет
угол по ориентации изображения (горизонтальное → 90°, вертикальное → 0°), `b` = +180°.

---

## Слой 4: Общий рендер квартиры (NEMOV_FSK_СЛОЙ_4)

API: `https://app.osmi-ai.ru/api/v1/prediction/2b1ee07c-839a-4ec1-8180-6f241e20a284`
Вход: `task_id` (строка)

| # | Файл | Назначение |
|---|------|------------|
| 1 | `node_L4_01_composite.js` | Stitch (Python) + Refine (Gemini Image dual) → composite в S3 |

**Шаги ноды:**
1. Загрузить `analysis.json` + список `L2_references/*.png`
2. POST `/stitch` — Python склеивает референсы по полигонам на холст схемы
3. Скачать `stitched.png` + `schema_x2.png` из S3
4. Gemini 3.1 Image dual (stitched + schema) — refine стен/проходов
5. Сохранить `composite.png` в S3

**Артефакты:** `fsk-generate-image/{task_id}/L4_composite/`
- `stitched.png` (~3 МБ — без AI, голая склейка)
- `composite.png` (~1 МБ — после AI-доработки)

---

## Оркестратор: Полный пайплайн (NEMOV_FSK_PIPELINE)

Последовательно вызывает все 4 слоя через Execute Flow ноды:

```
[Custom Function] парсит вход → запускает Слой 1
        ↓
[Execute Flow] Слой 1 → возвращает task_id
        ↓
[Execute Flow] Слой 2 (вход: task_id)
        ↓
[Execute Flow] Слой 3 (вход: task_id)
        ↓
[Execute Flow] Слой 4 (вход: task_id)
        ↓
[Direct Reply] финальный результат
```

**Передача task_id между Execute Flow:** в поле "Ввод" следующей ноды —
`{{customFunctionAgentflow_0}}` или `{{executeFlowAgentflow_N}}`.

**Время выполнения E2E (5 комнат):** ~155 секунд / 37 файлов в S3.

---

## Python Image Service

Файл: `image_service.py` — FastAPI микросервис обработки изображений.

| Эндпоинт | Назначение |
|----------|------------|
| POST `/upscale` | Апскейл x4 с лимитом по длинной стороне (Слой 1) |
| POST `/crop` | Кроп комнат по полигонам с блюром/контрастом/рамкой (Слой 1) |
| POST `/draw_polygons` | Визуализация полигонов на схеме (отладка Слоя 1) |
| POST `/rotate` | Апскейл + поворот референса (`side: a/b`) (Слой 3) |
| POST `/stitch` | Склейка референсов на холст по полигонам (Слой 4) |
| GET `/health` | Health-check |

**Запуск:**
```bash
uvicorn osmi_nodes.image_service:app --port 8003
```

**Тунель (постоянный сабдомен):**
```bash
tuna http 8003 --subdomain fsk-image-service
# → https://fsk-image-service.ru.tuna.am
```

---

## Структура S3-бакета

```
fsk-service/fsk-generate-image/{task_id}/
├── meta.json                          ← created_at + answers (Слой 1, нода 2)
├── L1_crops/
│   ├── schema_x2.png                  ← апскейл оригинала
│   ├── analysis.json                  ← LLM-анализ с полигонами
│   ├── L1_meta.json                   ← модель/тайминги/промпт
│   ├── schema_with_polygons.png       ← визуализация полигонов
│   └── 1_<room>_crop.png …            ← кропы комнат
├── L2_references/
│   └── <room>.png                     ← фотореалистичные виды сверху
├── L3_renders/
│   ├── <room>_prepared_<angle>deg.png ← от Python /rotate
│   └── <room>_side_a.png / _side_b.png← от Gemini Image
└── L4_composite/
    ├── stitched.png                   ← склейка без AI
    └── composite.png                  ← финал с AI-доработкой
```

---

## Инсайты OSMI Custom Function

- **return объект** (не `JSON.stringify`) — иначе OSMI ломает передачу между нодами
- **Input/Output Variables** — единственный рабочий способ передавать данные между
  Custom Function (`{{customFunctionAgentflow_0}}` в поле "Ввод" следующей ноды)
- **`$input`** — всегда оригинальный question, не return предыдущей ноды
- **`$flow.state`** — НЕ доступен в Custom Function
- **Завершающая нода** — должна быть Chain/Agent/Engine/Direct Reply, не Custom Function
- **nginx таймаут 240 сек** (изначально 60) → длинные операции дробить на параллельные через `Promise.all`
- **Большие base64 (>1МБ)** между нодами рвут тунель → отдавать S3-ключи, скачивать в следующей ноде
- **process.version и пр.** — sandbox NodeVM режет, использовать запрещено
