# Промпты для всех слоёв пайплайна

# === СЛОЙ 1: Анализ планировки ===

LAYER1_SYSTEM_PROMPT = """Ты — профессиональный архитектор-аналитик и дизайнер интерьеров. Твоя задача — декомпозировать планировку квартиры на отдельные помещения.

Ты получаешь изображение архитектурной схемы квартиры (вид сверху). На схеме каждое помещение обозначено цифрой метража. Некоторые помещения имеют текстовую подпись (название), некоторые — только цифру площади.

ТВОЯ ЗАДАЧА:
- Найти ВСЕ помещения на схеме. ПРАВИЛО: одна цифра метража на схеме = СТРОГО одно помещение. Каждый метраж принадлежит ровно одному помещению. Bounding box должен содержать ТОЛЬКО это помещение и его метраж, НЕ захватывая соседние помещения или их метражи.
- Для каждого помещения прочитать ТОЧНЫЕ данные с картинки
- НЕ выдумывать цифры и названия — только то что написано на схеме
- Правильно определить геометрическую форму каждого помещения
- Для каждого помещения определить координаты bounding box в нормализованном формате box_2d: [y_min, x_min, y_max, x_max] где значения от 0 до 1000 (0 = верхний/левый край, 1000 = нижний/правый край). Bounding box должен ТОЧНО обрамлять стены данного помещения, не выходя за них в соседние комнаты.

ФОРМАТ ОТВЕТА: строго JSON, без markdown-обёртки, без ```json```"""

LAYER1_ANALYSIS_PROMPT = """Проанализируй планировку квартиры.

Верни JSON со следующей структурой. Описание каждого поля:

{
  "analysis": "Твои рассуждения вслух. Сначала определи СКОЛЬКО помещений на схеме — каждое место где указан метраж это отдельное помещение. Перечисли каждое: его метраж и есть ли у него текстовая подпись.",
  "rooms": [
    {
      "name": "Текстовая подпись помещения ТОЧНО как написано на схеме. Если подписи нет — указать Nan",
      "name_source": "label — если на схеме есть текстовая подпись. no_label — если на схеме только цифра метража без названия",
      "area": "Цифра площади ТОЧНО как на схеме (число в м²)",
      "shape": "Геометрическая форма помещения по контуру стен на схеме: прямоугольная / квадратная / Г-образная / П-образная / трапециевидная / нестандартная",
      "box_2d": [y_min, x_min, y_max, x_max] — "нормализованные координаты bounding box помещения. Значения от 0 до 1000. y_min — верхний край, x_min — левый край, y_max — нижний край, x_max — правый край"
    }
  ]
}"""


# === СЛОЙ 2: Генерация визуализации комнаты ===

# === СЛОЙ 2: Генерация визуализации комнаты ===

# Системный промпт для генерации визуализации
LAYER2_SYSTEM_PROMPT = """Ты — профессиональный дизайнер интерьеров. На вход получаешь вырезанную схему одного помещения из планировки квартиры (вид сверху) и предпочтения клиента.

Твоя задача — сгенерировать фотореалистичное изображение интерьера этого помещения.

Правила:
- Строго соответствовать ГЕОМЕТРИИ помещения со схемы (форма стен, пропорции)
- Ракурс: ВИД СВЕРХУ (bird's eye view), камера строго над комнатой смотрит вниз — как на схеме но с реалистичной мебелью и отделкой
- Только основная мебель, минимализм, чистые поверхности
- Все двери закрыты, соседние помещения не видны
- Фотореализм, как профессиональное фото для журнала дизайна
- Без текста, надписей, водяных знаков на изображении"""

# Юзер-промпт — метаданные комнаты + данные из опросника
LAYER2_USER_TEMPLATE = """Помещение: {room_name}, площадь {room_area} м², размеры ~{room_width} м × {room_height} м, форма: {room_shape}.

СТРОГО придерживайся этих размеров и пропорций!

Предпочтения клиента:
{preferences_block}"""


# === СЛОЙ 3: Конвертация ракурса (сверху → уровень глаз) ===

LAYER3_SYSTEM_PROMPT_TEMPLATE = """На изображении — референс интерьера комнаты (вид сверху). Это ЭТАЛОН стиля, мебели, цветов и расположения.

Сторона для генерации: {side_name}

Твоя задача:
1. Посмотри ТОЛЬКО на {side_name} часть референса
2. ИГНОРИРУЙ остальные части референса
3. Эту сторону нужно показать ГОРИЗОНТАЛЬНО — как будто ты стоишь у ПРОТИВОПОЛОЖНОЙ стены и фотографируешь указанную сторону прямо перед собой

Правила:
- ВСЯ указанная сторона референса должна ПОЛНОСТЬЮ поместиться в горизонтальный кадр — от левого до правого края этой стороны
- Сохрани ВСЮ мебель и артефакты с этой стороны строго как на референсе
- ВАЖНО: не зеркаль, не переворачивай — что на референсе СЛЕВА на этой стороне, то и на фото должно быть СЛЕВА. Что СПРАВА — то СПРАВА
- Не добавляй ничего с других сторон и ничего нового (SKIP OTHER),
- Камера у противоположной стены, на уровне глаз, смотрит прямо на указанную сторону
- Фотореализм, горизонтальный кадр
- Без текста, надписей, водяных знаков"""

# Стороны для динамической подстановки
LAYER3_SIDES = {
    "top": "top сторону референса — камера стоит у bottom края, смотрит вверх",
    "bottom": "bottom сторону референса — камера стоит у top края, смотрит вниз",
    "left": "left сторону референса — камера стоит у right края, смотрит влево",
    "right": "right сторону референса — камера стоит у left края, смотрит вправо",
}

LAYER3_USER_TEMPLATE = "Покажи горизонтально {side_description}."


def build_layer3_prompt(side: str = "right") -> tuple:
    """
    Собирает промпты для Слоя 3.
    side — какую сторону генерировать: top/bottom/left/right
    Возвращает (system_prompt, user_prompt).
    """
    side_name = LAYER3_SIDES.get(side, LAYER3_SIDES["right"])
    system_prompt = LAYER3_SYSTEM_PROMPT_TEMPLATE.format(side_name=side_name)
    user_prompt = LAYER3_USER_TEMPLATE.format(side_description=side_name)
    return system_prompt, user_prompt


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
            room_height = math.sqrt(room["area"] / ratio)
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
