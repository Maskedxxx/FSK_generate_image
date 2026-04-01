"""
API — точка входа пайплайна генерации визуализаций интерьера.

Структура хранения:
    results/{task_id}/
        meta.json               — IP, UA, timestamp, answers
        input.jpg               — загруженная схема
        analysis.json           — результат Слоя 1
        crops/                  — вырезанные помещения
        references/             — референсы (вид сверху)
        artifacts.json          — артефакты по сторонам
        renders/                — горизонтальные фото

Поток:
    POST /layer1/analyze            — загрузка схемы + опросник → task_id (всё сохраняется)
    POST /layer2/generate/{task_id} — генерация референса комнаты (по индексу из task)
    POST /layer25/describe/{task_id} — описание артефактов (по индексу из task)
    POST /layer3/render/{task_id}   — горизонтальное фото (по индексу + сторона из task)
    POST /generate                  — полный пайплайн (всё за один вызов)
    GET  /status/{task_id}          — статус задачи
    GET  /result/{task_id}          — результаты

Запуск: uvicorn src.api:app --reload
"""

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import json
import uuid
import os
from datetime import datetime

from .questionnaire import QUESTIONS, validate_answers
from .pipeline import run_pipeline
from .layers.layer1_analyze import analyze_floorplan
from .layers.layer2_generate import generate_room
from .layers.layer25_describe import describe_all_sides
from .layers.layer3_render import render_side
from .logger import get_logger
from .config import FSK_API_KEY

app = FastAPI(
    title="FSK Generate Image",
    version="0.1.0",
    description="""
Сервис генерации визуализаций интерьера по архитектурной планировке квартиры.

**Поток работы:**
1. `POST /layer1/analyze` — загрузить схему + опросник → получить task_id и список комнат с crop'ами
2. `POST /layer2/generate/{task_id}` — по индексу комнаты → получить референс (вид сверху)
3. `POST /layer25/describe/{task_id}` — по индексу комнаты → получить артефакты по 4 сторонам
4. `POST /layer3/render/{task_id}` — по индексу + стороне → получить горизонтальное фото стены

**Или одним вызовом:**
- `POST /generate` — всё за один раз (фоновая задача), поллить `GET /status/{task_id}`
""",
)

log = get_logger("fsk.api")

# CORS — разрешаем фронту с любого домена (для прода ограничить)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище задач в памяти (для прода → Redis/БД)
tasks: dict = {}

# Корневая папка результатов
RESULTS_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
os.makedirs(RESULTS_BASE, exist_ok=True)

# Раздача файлов результатов: /files/{task_id}/crops/1_room.png
app.mount("/files", StaticFiles(directory=RESULTS_BASE), name="files")


# === ОБЩИЕ ===


@app.get("/", summary="Проверка работоспособности", tags=["Общие"])
def root():
    """Возвращает статус сервиса. Используется для health check."""
    return {"status": "ok", "service": "FSK Generate Image"}


@app.get("/questionnaire", summary="Структура опросника", tags=["Общие"])
def get_questionnaire():
    """
    Возвращает 9 вопросов опросника с вариантами ответов.
    Фронтенд использует для отображения формы.
    Все вопросы обязательны при вызове /generate или /layer1/analyze.
    """
    return QUESTIONS


# === ПОЛНЫЙ ПАЙПЛАЙН ===


@app.post("/generate", summary="Полный пайплайн генерации (фоновая задача)", tags=["Пайплайн"])
async def generate(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(..., description="Изображение планировки"),
    answers: str = Form(..., description="JSON с ответами опросника"),
):
    """
    Запускает полный пайплайн в фоне: Слой 1 → 2 → 2.5 → 3 для ВСЕХ комнат.

    **Вход:** image (файл JPG/PNG/SVG/HEIF/HEIC, до 20 МБ) + answers (JSON 9 ответов).
    **Выход:** `{task_id, status: "processing"}`. Поллить GET /status/{task_id}.
    **Результат:** GET /result/{task_id} когда status="done". Файлы в results/{task_id}/.
    """
    # Проверка API-ключа
    auth_error = _check_api_key(request)
    if auth_error:
        return auth_error

    # Валидация файла
    error = _validate_image(image)
    if error:
        return error

    # Валидация опросника
    validated, error = _validate_questionnaire(answers)
    if error:
        return error

    # Читаем и проверяем размер
    image_bytes = await image.read()
    if len(image_bytes) == 0:
        log.warning("Пустой файл (0 байт)")
        return JSONResponse(status_code=400, content={"error": "Файл пустой (0 байт)"})
    if len(image_bytes) > 20 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "Файл превышает максимальный размер 20 МБ"})

    # Создаём task
    task_id, task_dir = _create_task_dir()
    ext = os.path.splitext(image.filename)[1] if image.filename else ".jpg"
    image_path = os.path.join(task_dir, f"input{ext}")
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Сохраняем meta
    _save_meta(task_dir, request, {"type": "pipeline", "answers": validated})

    log.info(f"[{task_id}] Pipeline | {len(image_bytes) // 1024} KB")

    # Регистрируем
    tasks[task_id] = {
        "status": "processing",
        "created_at": datetime.now().isoformat(),
        "progress": "Запуск пайплайна...",
        "image_path": image_path,
        "task_dir": task_dir,
        "answers": validated,
        "result": None,
        "error": None,
    }

    background_tasks.add_task(_run_task, task_id)
    return {"task_id": task_id, "status": "processing"}


@app.get("/status/{task_id}", summary="Статус задачи", tags=["Пайплайн"])
def get_status(task_id: str):
    """
    **Вход:** task_id из POST /generate.
    **Выход:** status (processing/done/error), progress (текущий шаг), created_at.
    **Когда использовать:** поллить каждые 2-5 сек пока status != "done".
    """
    if task_id not in tasks:
        return JSONResponse(status_code=404, content={"error": "Задача не найдена"})

    task = tasks[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "created_at": task["created_at"],
        "error": task["error"],
    }


@app.get("/result/{task_id}", summary="Результаты генерации", tags=["Пайплайн"])
def get_result(task_id: str, request: Request):
    """
    **Вход:** task_id из POST /generate.
    **200:** `{rooms_count, rooms: [{name, area, reference, sides: {top,bottom,left,right}}]}`.
    **202:** ещё обрабатывается. **500:** ошибка. **404:** task не найден.
    """
    if task_id not in tasks:
        return JSONResponse(status_code=404, content={"error": "Задача не найдена"})

    task = tasks[task_id]

    if task["status"] == "processing":
        return JSONResponse(status_code=202, content={
            "task_id": task_id, "status": "processing", "progress": task["progress"],
        })

    if task["status"] == "error":
        return JSONResponse(status_code=500, content={
            "task_id": task_id, "status": "error", "error": task["error"],
        })

    return {"task_id": task_id, "status": "done", "result": _convert_result_paths(task["result"], request)}


# === СЛОИ (работают внутри существующего task) ===


@app.post("/layer1/analyze", summary="Слой 1: Анализ планировки → комнаты + crop'ы", tags=["Слои"])
async def layer1_analyze(
    request: Request,
    image: UploadFile = File(..., description="Изображение планировки"),
    answers: str = Form(..., description="JSON с ответами опросника"),
):
    """
    Первый шаг. Загружает схему, анализирует помещения, вырезает crop'ы.

    **Вход:** image (файл планировки) + answers (JSON опросника, сохраняется для Слоя 2).
    **Выход:** `{task_id, rooms: [{index, name, area, shape, has_crop}]}`.
    **Далее:** использовать task_id в /layer2/generate/{task_id}, /layer25/describe, /layer3/render.
    **Артефакты:** results/{task_id}/crops/ — вырезанные помещения + schema_with_polygons.png.
    """
    # Проверка API-ключа
    auth_error = _check_api_key(request)
    if auth_error:
        return auth_error

    # Валидация
    error = _validate_image(image)
    if error:
        return error

    validated, error = _validate_questionnaire(answers)
    if error:
        return error

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "Файл превышает 20 МБ"})

    # Создаём task
    task_id, task_dir = _create_task_dir()
    ext = os.path.splitext(image.filename)[1] if image.filename else ".jpg"
    image_path = os.path.join(task_dir, f"input{ext}")
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Сохраняем meta с опросником (для Слоя 2)
    _save_meta(task_dir, request, {"type": "layer1", "answers": validated})

    log.info(f"[{task_id}] Layer1 | {len(image_bytes) // 1024} KB")

    try:
        # Анализ + crop'ы
        crops_dir = os.path.join(task_dir, "L1_crops")
        result = analyze_floorplan(image_path, output_dir=crops_dir)

        # Сохраняем analysis.json в L1_crops
        _save_json(os.path.join(crops_dir, "analysis.json"), result)

        # Список комнат для фронта
        rooms_list = []
        for i, room in enumerate(result["rooms"]):
            rooms_list.append({
                "index": i,
                "name": room["name"],
                "area": room["area"],
                "shape": room["shape"],
                "has_crop": "crop_path" in room,
            })

        return {"status": "ok", "task_id": task_id, "rooms": rooms_list}

    except Exception as e:
        log.error(f"[{task_id}] Layer1 ошибка: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/layer2/generate/{task_id}", summary="Слой 2: Генерация референса (вид сверху)", tags=["Слои"])
async def layer2_generate(
    request: Request,
    task_id: str,
    room_index: int = Form(..., description="Индекс комнаты из Слоя 1"),
):
    """
    Двухпроходная генерация: пустая комната → наполнение мебелью по стилю из опросника.

    **Условие:** сначала вызвать POST /layer1/analyze (нужен task_id с crop'ами).
    **Вход:** task_id + room_index (из списка rooms Слоя 1).
    **Выход:** `{task_id, room_index, reference: путь к PNG}`.
    **Артефакты:** results/{task_id}/references/{name}.png + {name}_empty.png (промежуточный).
    """
    # Проверка API-ключа
    auth_error = _check_api_key(request)
    if auth_error:
        return auth_error

    # Загружаем данные task'а
    task_dir, analysis, answers, error = _load_task(task_id)
    if error:
        return error

    # Находим комнату по индексу
    room, error = _get_room(analysis, room_index, task_id)
    if error:
        return error

    room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
    log.info(f"[{task_id}] Layer2 | комната {room_index}: {room_name}")

    try:
        # Генерация
        refs_dir = os.path.join(task_dir, "L2_references")
        os.makedirs(refs_dir, exist_ok=True)
        safe_name = room_name.replace(" ", "_").replace("/", "-")
        ref_path = os.path.join(refs_dir, f"{safe_name}.png")

        generate_room(room, answers, room["crop_path"], ref_path)

        return {"status": "ok", "task_id": task_id, "room_index": room_index, "reference": _path_to_url(ref_path, request)}

    except Exception as e:
        log.error(f"[{task_id}] Layer2 ошибка: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/layer25/describe/{task_id}", summary="Слой 2.5: Описание артефактов по 4 сторонам", tags=["Слои"])
async def layer25_describe(
    request: Request,
    task_id: str,
    room_index: int = Form(..., description="Индекс комнаты"),
):
    """
    Режет референс на 4 стороны, для каждой определяет артефакты (мебель, двери, окна) с visibility full/partial.

    **Условие:** сначала вызвать /layer2/generate/{task_id} (нужен референс).
    **Вход:** task_id + room_index.
    **Выход:** `{task_id, room_index, sides: {top: [{name, visibility}], bottom: [...], left: [...], right: [...]}}`.
    **Артефакты:** results/{task_id}/artifacts/{name}.json.
    """
    auth_error = _check_api_key(request)
    if auth_error:
        return auth_error

    task_dir, analysis, answers, error = _load_task(task_id)
    if error:
        return error

    room, error = _get_room(analysis, room_index, task_id)
    if error:
        return error

    room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
    safe_name = room_name.replace(" ", "_").replace("/", "-")

    # Ищем референс
    ref_path = os.path.join(task_dir, "references", f"{safe_name}.png")
    if not os.path.exists(ref_path):
        return JSONResponse(status_code=400, content={
            "error": f"Референс не найден. Сначала вызовите /layer2/generate/{task_id}"
        })

    log.info(f"[{task_id}] Layer2.5 | комната {room_index}: {room_name}")

    try:
        artifacts_dir = os.path.join(task_dir, "L25_artifacts", safe_name)
        result = describe_all_sides(ref_path, room, artifacts_dir)

        # Сохраняем артефакты
        _save_json(os.path.join(task_dir, "L25_artifacts", f"{safe_name}.json"), result)

        return {"status": "ok", "task_id": task_id, "room_index": room_index, "sides": result}

    except Exception as e:
        log.error(f"[{task_id}] Layer2.5 ошибка: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/layer3/render/{task_id}", summary="Слой 3: Горизонтальное фото стены", tags=["Слои"])
async def layer3_render(
    request: Request,
    task_id: str,
    room_index: int = Form(..., description="Индекс комнаты"),
    side: str = Form(default="top", description="Сторона: top/bottom/left/right"),
):
    """
    Генерирует горизонтальное фото одной стены на уровне глаз по референсу + артефактам.

    **Условие:** сначала /layer2/generate (референс), опционально /layer25/describe (артефакты).
    **Вход:** task_id + room_index + side (top/bottom/left/right).
    **Выход:** `{task_id, room_index, side, image: путь к PNG}`.
    **Артефакты:** results/{task_id}/renders/{name}_{side}.png.
    **Без артефактов:** если /layer25 не вызывался — генерация без списка артефактов (менее точная).
    """
    auth_error = _check_api_key(request)
    if auth_error:
        return auth_error

    task_dir, analysis, answers, error = _load_task(task_id)
    if error:
        return error

    room, error = _get_room(analysis, room_index, task_id)
    if error:
        return error

    room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
    safe_name = room_name.replace(" ", "_").replace("/", "-")

    # Ищем референс
    ref_path = os.path.join(task_dir, "references", f"{safe_name}.png")
    if not os.path.exists(ref_path):
        return JSONResponse(status_code=400, content={
            "error": f"Референс не найден. Сначала вызовите /layer2/generate/{task_id}"
        })

    # Ищем артефакты (опционально)
    artifacts = []
    artifacts_path = os.path.join(task_dir, "L25_artifacts", f"{safe_name}.json")
    if os.path.exists(artifacts_path):
        with open(artifacts_path, "r", encoding="utf-8") as f:
            all_artifacts = json.load(f)
        artifacts = all_artifacts.get(side, [])

    log.info(f"[{task_id}] Layer3 | {room_name} → {side} | артефактов: {len(artifacts)}")

    try:
        renders_dir = os.path.join(task_dir, "L3_renders")
        os.makedirs(renders_dir, exist_ok=True)
        output_path = os.path.join(renders_dir, f"{safe_name}_{side}.png")

        render_side(ref_path, output_path, side, artifacts)

        return {"status": "ok", "task_id": task_id, "room_index": room_index, "side": side, "image": _path_to_url(output_path, request)}

    except Exception as e:
        log.error(f"[{task_id}] Layer3 ошибка: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# === ФОНОВЫЕ ЗАДАЧИ ===


def _run_task(task_id: str) -> None:
    """Запуск пайплайна в фоне."""
    task = tasks[task_id]

    def on_progress(message: str) -> None:
        task["progress"] = message

    try:
        result = run_pipeline(
            image_path=task["image_path"],
            answers=task["answers"],
            output_dir=task["task_dir"],
            on_progress=on_progress,
        )

        task["status"] = "done"
        task["progress"] = "Готово"
        task["result"] = result
        log.info(f"[{task_id}] Pipeline завершён: {result['rooms_count']} комнат")

    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
        task["progress"] = f"Ошибка: {str(e)}"
        log.error(f"[{task_id}] Pipeline ошибка: {e}")


# === УТИЛИТЫ ===


def _create_task_dir() -> tuple[str, str]:
    """Создаёт results/{date}_{task_id}/. Возвращает (task_id, task_dir)."""
    from datetime import datetime
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    task_id = f"{date_prefix}_{uuid.uuid4().hex[:8]}"
    task_dir = os.path.join(RESULTS_BASE, task_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_id, task_dir


def _save_meta(task_dir: str, request: Request, extra: dict = None) -> None:
    """Сохраняет meta.json."""
    meta = {
        "created_at": datetime.now().isoformat(),
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
    }
    if extra:
        meta.update(extra)
    _save_json(os.path.join(task_dir, "meta.json"), meta)


def _save_json(path: str, data: dict) -> None:
    """Сохраняет dict в JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_task(task_id: str) -> tuple:
    """
    Загружает данные task'а с диска.

    Возвращает:
        (task_dir, analysis, answers, error)
        error = None если ок, JSONResponse если ошибка
    """
    task_dir = os.path.join(RESULTS_BASE, task_id)

    # Проверяем что task существует
    if not os.path.exists(task_dir):
        return None, None, None, JSONResponse(status_code=404, content={"error": f"Task {task_id} не найден"})

    # Загружаем analysis.json
    analysis_path = os.path.join(task_dir, "L1_crops", "analysis.json")
    if not os.path.exists(analysis_path):
        return None, None, None, JSONResponse(status_code=400, content={
            "error": "analysis.json не найден. Сначала вызовите /layer1/analyze"
        })

    with open(analysis_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    # Загружаем answers из meta.json
    meta_path = os.path.join(task_dir, "meta.json")
    answers = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        answers = meta.get("answers", {})

    return task_dir, analysis, answers, None


def _get_room(analysis: dict, room_index: int, task_id: str) -> tuple:
    """
    Находит комнату по индексу в analysis.

    Возвращает:
        (room, error) — room dict или JSONResponse с ошибкой
    """
    rooms = analysis.get("rooms", [])

    if room_index < 0 or room_index >= len(rooms):
        return None, JSONResponse(status_code=400, content={
            "error": f"Индекс комнаты {room_index} вне диапазона (0-{len(rooms) - 1})"
        })

    room = rooms[room_index]

    if "crop_path" not in room:
        return None, JSONResponse(status_code=400, content={
            "error": f"Комната {room_index} не имеет crop'а"
        })

    return room, None


def _path_to_url(file_path: str, request: Request) -> str:
    """
    Конвертирует абсолютный путь к файлу в URL для фронта.
    results/abc123/crops/1_room.png → http://host/files/abc123/crops/1_room.png
    """
    if not file_path or not isinstance(file_path, str):
        return file_path
    # Вырезаем путь относительно RESULTS_BASE
    try:
        rel_path = os.path.relpath(file_path, RESULTS_BASE)
        return f"{request.base_url}files/{rel_path}"
    except ValueError:
        return file_path


def _convert_result_paths(result: dict, request: Request) -> dict:
    """
    Рекурсивно заменяет абсолютные пути в результатах на URL.
    """
    if isinstance(result, dict):
        return {k: _convert_result_paths(v, request) for k, v in result.items()}
    elif isinstance(result, list):
        return [_convert_result_paths(item, request) for item in result]
    elif isinstance(result, str) and result.startswith("/") and os.path.exists(result):
        return _path_to_url(result, request)
    return result


def _check_api_key(request: Request):
    """
    Проверяет API-ключ в заголовке X-API-Key.
    Возвращает None если ок, JSONResponse(401) если нет.
    """
    api_key = request.headers.get("X-API-Key", "")
    if api_key != FSK_API_KEY:
        log.warning(f"Неверный API-ключ: {api_key[:10]}...")
        return JSONResponse(status_code=401, content={"error": "Unauthorized. Требуется заголовок X-API-Key."})
    return None


def _validate_image(image: UploadFile):
    """Валидация формата. Возвращает None или JSONResponse с ошибкой."""
    allowed = {".jpg", ".jpeg", ".png", ".svg", ".heif", ".heic"}
    ext = os.path.splitext(image.filename)[1].lower() if image.filename else ""
    if ext not in allowed:
        log.warning(f"Неподдерживаемый формат: {ext}")
        return JSONResponse(status_code=400, content={
            "error": "Неподдерживаемый формат файла. Допустимые: JPG, JPEG, PNG, SVG, HEIF, HEIC"
        })
    return None


def _validate_questionnaire(answers_str: str) -> tuple:
    """Парсит и валидирует опросник. Возвращает (validated, None) или (None, error)."""
    try:
        answers_dict = json.loads(answers_str)
    except json.JSONDecodeError:
        return None, JSONResponse(status_code=400, content={"error": "Невалидный JSON в answers"})

    try:
        validated = validate_answers(answers_dict)
        return validated, None
    except ValueError as e:
        return None, JSONResponse(status_code=400, content={"error": str(e)})
