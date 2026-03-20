# Тест полного пайплайна: планировка + опросник → визуализации
# Запуск: python -m tests.test_pipeline

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import run_pipeline
from src.questionnaire import TEST_ANSWERS

IMAGE_PATH = "/Users/mask/Downloads/конеткст_для_агента/Валидные/Снимок экрана 2026-03-10 130257.jpg"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "pipeline_test")

if __name__ == "__main__":
    result = run_pipeline(IMAGE_PATH, TEST_ANSWERS, OUTPUT_DIR)

    print(f"\n=== ИТОГ ===")
    print(f"Помещений: {len(result['rooms'])}")
    for r in result["rooms"]:
        room = r["room"]
        name = room["name"] if room["name"] != "Nan" else f"(без имени, {room['area']} м²)"
        print(f"  {name} → {r['image_path']}")
