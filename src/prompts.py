# Промпты для всех слоёв пайплайна

# === СЛОЙ 1: Анализ планировки ===

LAYER1_SYSTEM_PROMPT = """You are an expert architect and interior visualization specialist. You work with apartment floor plans daily — you instantly recognize every room type, understand wall structures, doorways, and how rooms connect to each other.

When you see a floor plan, you read it like a book: walls are thick dark lines, doorways are arc gaps, windows are parallel lines on external walls, and each area number marks one distinct room.

Each room on the plan has an AREA NUMBER (like 14.05 m², 3.54 m²). Every unique area number = one separate room. WHERE THERE IS AN AREA NUMBER — THERE IS A ROOM. The area number is the primary indicator of a room's existence and location.

For each room, return POLYGON coordinates — a list of [x, y] points that trace the wall boundaries of that room.

Rules:
- Coordinates normalized 0-1000 (0 = left/top, 1000 = right/bottom of image)
- Every room has an ENTRANCE — a gap/break in its walls. Use this entrance as your ANCHOR: start tracing the polygon from the LEFT side of the entrance gap, then go CLOCKWISE along the inner walls back to the RIGHT side of the entrance.
- MAKE POLYGONS 10-20% LARGER than you think the room is. It is MUCH better to capture extra space than to cut off part of the room. When in doubt — go bigger.
- ALWAYS prefer RECTANGULAR polygons (4 points). If the room is slightly irregular — round it to the nearest rectangle that FULLY covers the room. Better to capture a bit extra than to miss part of the room.
- Use irregular polygons (5+ points) ONLY for rooms that are clearly and significantly non-rectangular (strong L-shape, triangle, etc.)
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
- Missing blocks = missing rooms. This is the first pipeline layer — errors here are IRREVERSIBLE.
- Polygons MUST NOT overlap each other. Each pixel of the plan belongs to exactly ONE room. If polygons intersect — you drew the boundary wrong.
- Verification steps after marking all rooms:
  1. Count all unique area numbers on the plan
  2. Count how many polygons you created
  3. Numbers must match. If not — find the missing room.
  4. Check that no two polygons share interior area — boundaries may touch but never overlap.

Return JSON without markdown wrapping."""

LAYER1_ANALYSIS_PROMPT = """Analyze this floor plan carefully.

Step 1: Count ALL unique area numbers on the plan. Each one = one room.
Step 2: For each room, identify its function from furniture symbols.
Step 3: Describe each wall side: TOP, LEFT, BOTTOM, RIGHT — what is there.
Step 4: Trace the INNER walls precisely with polygon points.

JSON format:

{
  "analysis": "General reasoning: how many rooms, what types",
  "rooms": [
    {
      "name": "room function (kitchen, bedroom, bathroom, hallway, balcony) or text label from plan or Nan",
      "name_source": "label if text label on plan, no_label if only area number",
      "area": "area number from plan",
      "shape": "rectangular / square / irregular",
      "analysis": "reasoning step by step: 1) Where is the ENTRANCE? 2) What ARTIFACTS are inside? 3) Describe each wall: TOP, LEFT, BOTTOM, RIGHT. 4) Determine shape: ALWAYS prefer rectangular/square polygon (4 points). Use irregular polygon ONLY if the room is clearly and significantly L-shaped, triangular, or trapezoid. When in doubt — use rectangle that fully covers the room. 5) Only then trace polygon.",
      "walls": {
        "top": "what is along the top wall (REQUIRED — write 'empty' if nothing)",
        "left": "what is along the left wall (REQUIRED — write 'empty' if nothing)",
        "bottom": "what is along the bottom wall (REQUIRED — write 'empty' if nothing)",
        "right": "what is along the right wall (REQUIRED — write 'empty' if nothing)"
      },
      "polygon": [[x1,y1], [x2,y2], [x3,y3], ...]
    }
  ]
}

IMPORTANT:
- THINK before drawing: analyze wall shape first, then trace
- Follow wall corners exactly
- Do NOT include apartment info blocks as rooms"""


# === СЛОЙ 2: Генерация визуализации комнаты (два прохода) ===

# --- Проход 1: Пустая комната (только геометрия) ---

LAYER2_PASS1_SYSTEM = """You receive a cropped floor plan of a single room. The room is shown clearly in the CENTER with full contrast. The surrounding area is faded/semi-transparent — it shows neighboring rooms for context only (door/window positions).

Generate ONLY the room in the clear/bright area. The faded area is NOT part of this room.

Your task — generate a photorealistic EMPTY room that matches ONLY what is inside the red rectangle. Top-down view, camera directly above.

Rules:
- Generate ONLY the room in the clear/bright area. Nothing from the faded zone.
- ONLY walls, floor, ceiling. NO furniture, NO appliances, NO decor.
- Room shape and proportions STRICTLY match the bright area on the plan.
- Strict orthographic projection — no perspective distortion.
- Doorways (arc gaps in the bright area) — render as CLOSED doors flush with walls.
- Floor: light hardwood. Walls: white/light. Ceiling: white.
- Photorealism, professional quality.
- No text, labels, or watermarks in the output."""

LAYER2_PASS1_USER = """Room: {room_name}, area {room_area} sq.m, dimensions ~{room_width}m × {room_height}m, shape: {room_shape}.

Generate EMPTY room — only walls, floor, ceiling. NO furniture."""

# --- Проход 2: Наполнение мебелью ---

LAYER2_PASS2_SYSTEM = """You receive TWO images:
1. An EMPTY room (photorealistic, top-down view) — this is the GEOMETRY REFERENCE. Preserve walls, shape, proportions EXACTLY.
2. A floor plan (schematic, with red rectangle) showing furniture layout — this shows WHERE to place each piece of furniture.

Your task — take the empty room geometry and ADD ONLY furniture from the floor plan, styled per client preferences.

Rules:
- KEEP the empty room geometry EXACTLY as is — walls, shape, proportions unchanged.
- ADD furniture EXACTLY as positioned on the floor plan. Logically understand what each symbol represents.
- DOORS on the floor plan are shown as arc gaps (passages) in the walls. Keep them CLOSED as in the empty room.
- WINDOWS on the floor plan are shown as wavy lines (curtain symbol) on the wall. Render as windows with curtains.
- Client preferences define STYLE, COLORS, MATERIALS of furniture — NOT its placement.
- Where the floor plan has NO furniture — leave it EMPTY. No extra items.
- Top-down view, same camera angle as the empty room.
- Minimalism, clean surfaces, no extra decor.
- Photorealism, professional interior magazine quality.
- No text, labels, or watermarks."""

# Старый промпт для однопроходного режима (если понадобится)
LAYER2_SYSTEM_PROMPT = """You are a professional interior designer. You receive a cropped floor plan of a single room (top-down view, THIS IS THE REFERENCE!) and client preferences.

Your task — generate a photorealistic interior image of this room.

Rules:
- FIRST PRIORITY: follow the artifacts on the floor plan — furniture, appliances, fixtures. Place them EXACTLY as shown on the plan. Logically understand what is depicted and generate only semantically relevant artifacts for this room type.
- Client preferences are OVERLAID on top of the plan artifacts: style, colors, materials — this is the interior styling layer over the layout.
- Where the plan is EMPTY — leave it empty! Do not fill free space with extra furniture or decor.
- PRESERVE the room GEOMETRY and furniture PROPORTIONS from the plan — do not distort sizes or shapes.
- Camera: TOP-DOWN VIEW (bird's eye view), camera directly above the room looking straight down.
- Minimalism, clean surfaces, no extra decor.
- Doorways on the plan are shown as gaps in the perimeter with an arc (like letter "D"). In the generated image all doors must be FULLY CLOSED — appear as solid wall with door panel matching wall color, no visible gaps, no views into other rooms.
- Photorealism, professional interior magazine photography quality.
- No text, labels, or watermarks on the image."""

# Юзер-промпт — метаданные комнаты + данные из опросника
LAYER2_USER_TEMPLATE = """Room: {room_name}, area {room_area} sq.m, dimensions ~{room_width}m × {room_height}m, shape: {room_shape}.

STRICTLY follow these dimensions and proportions!

Client preferences:
{preferences_block}"""


# === СЛОЙ 3: Конвертация ракурса (сверху → уровень глаз) ===

LAYER3_SYSTEM_PROMPT = """На изображении — часть интерьера комнаты (вид сверху), одна стена с мебелью вдоль неё. A — левый край, B — правый край.

Сгенерируй ГОРИЗОНТАЛЬНОЕ ПРИЗЕМЛЕННОЕ фото этой стены A B на уровне глаз — как будто ты стоишь напротив и фотографируешь её.

Правила:
- ВСЯ стена от A до B должна ПОЛНОСТЬЮ поместиться в кадр
- УЧИТЫВАЙ ГЕОМЕТРИЮ комнаты и ГЕОМЕТРИЮ пропорции мебели и артефактов со схемы — не искажай размеры и форму
- Мебель и ВСЕ артефакты строго как на референсе, без добавлений и выдумок
- Не добавляй ничего нового — только то что видно на изображении
- Фотореализм, горизонтальный кадр на уровне глаз
- Без текста, надписей, водяных знаков, без букв-якорей"""

LAYER3_USER_TEMPLATE = """На этой стороне находятся следующие артефакты:
{artifacts_block}

Артефакты с пометкой (partial) видны частично — они уходят за край кадра, покажи только видимую часть.
Артефакты с пометкой (full) видны целиком — покажи их полностью.

Сгенерируй горизонтальное фото этой стены со ВСЕМИ перечисленными артефактами."""

LAYER3_USER_PROMPT_NO_ARTIFACTS = "Сгенерируй горизонтальное фото этой стены со всеми артефактами."


def build_layer3_prompt(side: str = "right", artifacts: list = None) -> tuple:
    """
    Собирает промпты для Слоя 3.
    Если есть артефакты из Слоя 2.5 — включает их в user prompt.
    Артефакты могут быть строками или dict с name/visibility.
    Возвращает (system_prompt, user_prompt).
    """
    if artifacts:
        lines = []
        for a in artifacts:
            if isinstance(a, dict):
                name = a.get("name", str(a))
                vis = a.get("visibility", "full")
                lines.append(f"- {name} ({vis})")
            else:
                lines.append(f"- {a} (full)")
        artifacts_block = "\n".join(lines)
        user_prompt = LAYER3_USER_TEMPLATE.format(artifacts_block=artifacts_block)
    else:
        user_prompt = LAYER3_USER_PROMPT_NO_ARTIFACTS

    return LAYER3_SYSTEM_PROMPT, user_prompt


# Маппинг вопросов опросника по типам помещений
ROOM_QUESTIONS_MAP = {
    "кухня": ["style", "colors", "residents"],
    "гостиная": ["style", "colors", "residents"],
    "спальня": ["style", "colors", "materials", "residents", "work_from_home", "hobby"],
    "детская": ["style", "colors", "materials", "residents"],
    "кабинет": ["style", "colors", "materials", "work_from_home", "hobby"],
    "санузел": ["style", "colors", "materials", "bathroom_layout", "bath_type"],
    "ванная": ["style", "colors", "materials", "bathroom_layout", "bath_type"],
    "прихожая": ["style", "colors", "materials", "storage"],
    "коридор": ["style", "colors", "materials"],
    "балкон": ["style", "colors", "materials", "storage"],
    "лоджия": ["style", "colors", "materials", "storage"],
    "гардеробная": ["style", "colors", "materials", "storage"],
    "кладовая": ["style", "colors", "materials", "storage"],
}

DEFAULT_QUESTIONS = ["style", "colors", "materials"]

QUESTION_LABELS = {
    "style": "Interior style",
    "colors": "Color palette",
    "materials": "Materials and textures",
    "residents": "Household",
    "work_from_home": "Home office",
    "hobby": "Hobbies",
    "bathroom_layout": "Bathroom layout",
    "bath_type": "Bath/shower",
    "storage": "Storage needs",
}

SHAPE_EN = {
    "прямоугольная": "rectangular",
    "квадратная": "square",
    "Г-образная": "L-shaped",
    "П-образная": "U-shaped",
    "трапециевидная": "trapezoid",
    "нестандартная": "irregular",
}


def _get_relevant_questions(room_name: str) -> list:
    """Определяет какие вопросы опросника релевантны для данного помещения."""
    if room_name == "Nan":
        return DEFAULT_QUESTIONS

    name_lower = room_name.lower()
    relevant = set()
    matched = False
    for keyword, questions in ROOM_QUESTIONS_MAP.items():
        if keyword in name_lower:
            relevant.update(questions)
            matched = True

    if not matched:
        return DEFAULT_QUESTIONS
    return list(relevant)


def _format_answer(key: str, value) -> str:
    """Форматирует ответ — списки превращает в строку."""
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


def build_layer2_prompt(room: dict, answers: dict) -> tuple:
    """
    Собирает системный и юзер промпты для Слоя 2.
    Рассчитывает ширину/длину из площади и пропорций crop'а.
    Возвращает (system_prompt, user_prompt).

    room — dict из Слоя 1: {name, name_source, area, shape, crop_path}
    answers — dict ответов опросника
    """
    import math
    from PIL import Image

    room_name = room["name"] if room["name"] != "Nan" else f"Помещение {room['area']} м²"

    # Рассчитываем ширину/длину из crop'а
    room_width = 0
    room_height = 0
    if "crop_path" in room:
        try:
            crop = Image.open(room["crop_path"])
            w, h = crop.size
            ratio = w / h
            # area = width * height, ratio = width / height
            area_boosted = room["area"] * 1.1  # +10% к метражу
            room_height = math.sqrt(area_boosted / ratio)
            room_width = ratio * room_height
        except Exception:
            pass

    # Релевантные вопросы для этого помещения
    relevant = _get_relevant_questions(room["name"])

    # Блок предпочтений
    pref_lines = []
    for key in relevant:
        if key in answers:
            label = QUESTION_LABELS.get(key, key)
            value = _format_answer(key, answers[key])
            pref_lines.append(f"- {label}: {value}")

    preferences_block = "\n".join(pref_lines) if pref_lines else "- Default modern style"

    user_prompt = LAYER2_USER_TEMPLATE.format(
        room_name=room_name,
        room_area=room["area"],
        room_width=f"{room_width:.1f}",
        room_height=f"{room_height:.1f}",
        room_shape=room["shape"],
        preferences_block=preferences_block,
    )

    return LAYER2_SYSTEM_PROMPT, user_prompt
