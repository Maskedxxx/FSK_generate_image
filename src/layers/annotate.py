# Аннотирование референса — якоря (A, B, C, D) + линии центра + поворот
# Используется между Слоем 2 и Слоем 3

from PIL import Image, ImageDraw, ImageFont


def prepare_for_layer3(reference_path: str, output_path: str, side: str = "top") -> str:
    """
    Подготавливает референс для Слоя 3:
    1. Обрезает нужную половину референса
    2. Поворачивает чтобы стена всегда была СВЕРХУ (как top)
    3. Ставит якоря A, B сверху

    Модель всегда видит: стена сверху, камера снизу из центра.

    Повороты после обрезки:
    - top: без поворота (уже правильно)
    - bottom: поворот 180° (низ становится верхом)
    - right: поворот 90° по часовой (правая становится верхом)
    - left: поворот 270° по часовой = 90° против часовой (левая становится верхом)

    Аргументы:
        reference_path: путь к референсу из Слоя 2
        output_path: путь для сохранения
        side: top/bottom/left/right

    Возвращает:
        путь к подготовленному изображению
    """
    img = Image.open(reference_path)
    w, h = img.size

    # Обрезаем нужную половину и поворачиваем
    if side == "top":
        crop = img.crop((0, 0, w, h // 2))
        # Без поворота
    elif side == "bottom":
        crop = img.crop((0, h // 2, w, h))
        crop = crop.rotate(180, expand=True)
    elif side == "left":
        crop = img.crop((0, 0, w // 2, h))
        crop = crop.rotate(270, expand=True)
    elif side == "right":
        crop = img.crop((w // 2, 0, w, h))
        crop = crop.rotate(90, expand=True)
    else:
        crop = img.crop((0, 0, w, h // 2))

    # Рисуем якоря A и B сверху
    draw = ImageDraw.Draw(crop)
    cw, ch = crop.size
    color = (255, 0, 0)

    font_size = max(20, min(cw, ch) // 10)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

    margin = 10
    draw.text((margin, margin), "A", fill=color, font=font)
    draw.text((cw - font_size - margin, margin), "B", fill=color, font=font)

    crop.save(output_path)
    return output_path
