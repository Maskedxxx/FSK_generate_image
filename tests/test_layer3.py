# Тест Слоя 3: горизонтальная генерация стороны комнаты
# Запуск: python -m tests.test_layer3 <путь к референсу> [сторона: top/bottom/left/right]
# Пример: python -m tests.test_layer3 results/layer2_XXXXX/Кухня-гостиная.png right
# Без аргументов: берёт последний результат Слоя 2, сторона right

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layers.render import render_side

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def find_latest_layer2_image():
    """Находит последнюю картинку из Слоя 2."""
    dirs = [d for d in os.listdir(RESULTS_DIR) if d.startswith("layer2_") and os.path.isdir(os.path.join(RESULTS_DIR, d))]
    if not dirs:
        return None
    dirs.sort()
    latest_dir = os.path.join(RESULTS_DIR, dirs[-1])
    pngs = [f for f in os.listdir(latest_dir) if f.endswith(".png")]
    if not pngs:
        return None
    return os.path.join(latest_dir, pngs[0])


def main():
    # Референс
    if len(sys.argv) > 1:
        reference_path = sys.argv[1]
    else:
        reference_path = find_latest_layer2_image()

    # Сторона
    side = sys.argv[2] if len(sys.argv) > 2 else "right"

    if not reference_path or not os.path.exists(reference_path):
        print("Нет референса. Укажите путь или запустите Слой 2 сначала.")
        print("Использование: python -m tests.test_layer3 <путь> [top|bottom|left|right]")
        return

    print(f"Референс: {reference_path}")
    print(f"Сторона: {side}")

    # Подпапка сессии
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RESULTS_DIR, f"layer3_{session_id}")
    os.makedirs(session_dir, exist_ok=True)

    ref_name = os.path.splitext(os.path.basename(reference_path))[0]
    output_path = os.path.join(session_dir, f"{ref_name}_{side}.png")

    print("Генерация...")
    render_side(reference_path, output_path, side)
    print(f"Сохранено: {output_path}")


if __name__ == "__main__":
    main()
