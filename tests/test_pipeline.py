"""
Unit-тест пайплайна (с моками API).

Тестирует:
    - run_pipeline() — полный пайплайн: Слой 1 → 2 → 2.5 → 3
    - process_room() — обработка одной комнаты
    - Прогресс-колбэк вызывается
    - Результат содержит все комнаты с референсами и сторонами
    - Комнаты без crop пропускаются

Запуск: pytest tests/test_pipeline.py -v
"""

import sys
import os
import json
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline import run_pipeline, process_room
from src.questionnaire import TEST_ANSWERS, validate_answers


# === ФИКСТУРЫ ===


FAKE_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

FAKE_ANALYSIS = {
    "analysis": "Тест: 2 помещения",
    "rooms": [
        {
            "name": "Кухня-гостиная",
            "name_source": "label",
            "area": 17.7,
            "shape": "прямоугольная",
            "box_2d": [76, 347, 493, 915],
            "crop_path": None,  # заполняется в фикстуре
        },
        {
            "name": "Спальня",
            "name_source": "label",
            "area": 14.8,
            "shape": "прямоугольная",
            "box_2d": [496, 350, 946, 804],
            "crop_path": None,
        },
    ],
}

FAKE_ARTIFACTS = {
    "top": [{"name": "шкаф", "visibility": "full"}],
    "bottom": [{"name": "диван", "visibility": "full"}],
    "left": [{"name": "стол", "visibility": "partial"}],
    "right": [{"name": "кресло", "visibility": "full"}],
}


@pytest.fixture
def test_image(tmp_path):
    """Создаёт тестовое изображение планировки."""
    img = Image.new("RGB", (500, 400), color="white")
    path = tmp_path / "input.jpg"
    img.save(path)
    return str(path)


@pytest.fixture
def valid_answers():
    return validate_answers(TEST_ANSWERS)


@pytest.fixture
def mock_all_layers(tmp_path):
    """Мокает все слои — не вызывает реальные API."""

    def mock_analyze(image_path, output_dir=None):
        """Мок Слоя 1 — возвращает фейковый анализ с crop'ами."""
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        analysis = json.loads(json.dumps(FAKE_ANALYSIS))
        for room in analysis["rooms"]:
            # Создаём фейковые crop-файлы
            safe = room["name"].replace(" ", "_").replace("/", "-")
            crop_path = os.path.join(output_dir or str(tmp_path), f"{safe}_crop.png")
            Image.new("RGB", (200, 150), "grey").save(crop_path)
            room["crop_path"] = crop_path
        return analysis

    def mock_generate(room, answers, crop_path, output_path):
        """Мок Слоя 2 — создаёт фейковый референс."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Создаём и empty и финальный
        empty_path = output_path.replace(".png", "_empty.png")
        Image.new("RGB", (400, 300), "beige").save(empty_path)
        Image.new("RGB", (400, 300), "beige").save(output_path)
        return output_path

    def mock_describe(ref_path, room, output_dir):
        """Мок Слоя 2.5 — возвращает фейковые артефакты."""
        os.makedirs(output_dir, exist_ok=True)
        return dict(FAKE_ARTIFACTS)

    def mock_render(ref_path, output_path, side, artifacts=None):
        """Мок Слоя 3 — создаёт фейковое горизонтальное фото."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        Image.new("RGB", (600, 400), "lightblue").save(output_path)
        return output_path

    with patch("src.pipeline.analyze_floorplan", side_effect=mock_analyze), \
         patch("src.pipeline.generate_room", side_effect=mock_generate), \
         patch("src.pipeline.describe_all_sides", side_effect=mock_describe), \
         patch("src.pipeline.render_side", side_effect=mock_render):
        yield


# === ТЕСТЫ: run_pipeline ===


def test_pipeline_full(test_image, valid_answers, mock_all_layers, tmp_path):
    """Полный пайплайн — 2 комнаты, все слои."""
    output_dir = str(tmp_path / "task")
    result = run_pipeline(test_image, valid_answers, output_dir)

    # Проверяем структуру результата
    assert result["rooms_count"] == 2
    assert len(result["rooms"]) == 2

    # Каждая комната имеет референс и 4 стороны
    for room in result["rooms"]:
        assert "name" in room
        assert "reference" in room
        assert "sides" in room
        assert set(room["sides"].keys()) == {"top", "bottom", "left", "right"}


def test_pipeline_creates_files(test_image, valid_answers, mock_all_layers, tmp_path):
    """Пайплайн создаёт файлы в правильной структуре."""
    output_dir = str(tmp_path / "task")
    run_pipeline(test_image, valid_answers, output_dir)

    # analysis.json
    assert os.path.exists(os.path.join(output_dir, "analysis.json"))

    # crops/
    assert os.path.exists(os.path.join(output_dir, "crops"))

    # references/
    refs_dir = os.path.join(output_dir, "references")
    assert os.path.exists(refs_dir)
    assert len(os.listdir(refs_dir)) >= 2  # 2 комнаты × (ref + empty)

    # renders/
    renders_dir = os.path.join(output_dir, "renders")
    assert os.path.exists(renders_dir)
    assert len(os.listdir(renders_dir)) >= 8  # 2 комнаты × 4 стороны


def test_pipeline_progress_callback(test_image, valid_answers, mock_all_layers, tmp_path):
    """Колбэк прогресса вызывается."""
    output_dir = str(tmp_path / "task")
    progress_messages = []

    def on_progress(msg):
        progress_messages.append(msg)

    run_pipeline(test_image, valid_answers, output_dir, on_progress=on_progress)

    # Должны быть сообщения от каждого слоя
    assert len(progress_messages) > 0
    assert any("Слой 1" in m for m in progress_messages)
    assert any("Слой 2" in m for m in progress_messages)
    assert any("Готово" in m for m in progress_messages)


def test_pipeline_skips_rooms_without_crop(test_image, valid_answers, tmp_path):
    """Комнаты без crop пропускаются."""
    # Мок Слоя 1 без crop_path
    analysis_no_crop = {
        "analysis": "test",
        "rooms": [
            {"name": "Room1", "area": 10.0, "shape": "прямоугольная", "box_2d": [0, 0, 500, 500]},
        ],
    }

    with patch("src.pipeline.analyze_floorplan", return_value=analysis_no_crop):
        output_dir = str(tmp_path / "task")
        result = run_pipeline(test_image, valid_answers, output_dir)

    assert result["rooms_count"] == 0


# === ТЕСТЫ: process_room ===


def test_process_room(valid_answers, mock_all_layers, tmp_path):
    """Обработка одной комнаты — все 3 слоя."""
    output_dir = str(tmp_path / "task")
    os.makedirs(output_dir, exist_ok=True)

    # Создаём фейковый crop
    crop_path = str(tmp_path / "crop.png")
    Image.new("RGB", (200, 150), "grey").save(crop_path)

    room = {
        "name": "Кухня-гостиная",
        "area": 17.7,
        "shape": "прямоугольная",
        "crop_path": crop_path,
    }

    result = process_room(room, valid_answers, output_dir)

    assert result["name"] == "Кухня-гостиная"
    assert result["area"] == 17.7
    assert "reference" in result
    assert set(result["sides"].keys()) == {"top", "bottom", "left", "right"}
