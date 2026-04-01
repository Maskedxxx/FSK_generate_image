"""
Unit-тесты Слоя 2: генерация референса.

Тестирует:
    - _upscale_and_encode() — масштабирование (маленький, большой, битый файл)
    - _extract_image() — извлечение base64 (с изображением, без, отказ модели)
    - generate_room() — полный вызов (с моком API)
    - build_layer2_prompt() — маппинг вопросов по типу комнаты

Запуск: pytest tests/layers/test_layer2.py -v
"""

import sys
import os
import json
import pytest
from PIL import Image
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.layers.layer2_generate import _upscale_and_encode, generate_room
from src.prompts import build_layer2_prompt
from src.questionnaire import TEST_ANSWERS, validate_answers


# === ФИКСТУРЫ ===


@pytest.fixture
def small_crop(tmp_path):
    """Создаёт маленький crop 100x80 px."""
    img = Image.new("RGB", (100, 80), color="grey")
    path = tmp_path / "small_crop.png"
    img.save(path)
    return str(path)


@pytest.fixture
def large_crop(tmp_path):
    """Создаёт большой crop 1200x900 px."""
    img = Image.new("RGB", (1200, 900), color="grey")
    path = tmp_path / "large_crop.png"
    img.save(path)
    return str(path)


@pytest.fixture
def valid_room():
    """Метаданные комнаты из Слоя 1."""
    return {"name": "Кухня-гостиная", "name_source": "label", "area": 17.7, "shape": "прямоугольная"}


@pytest.fixture
def nan_room():
    """Комната без имени."""
    return {"name": "Nan", "name_source": "no_label", "area": 3.7, "shape": "прямоугольная"}


@pytest.fixture
def valid_answers():
    """Валидированные ответы опросника."""
    return validate_answers(TEST_ANSWERS)


# === ТЕСТЫ: _upscale_and_encode ===


def test_upscale_small_crop(small_crop):
    """Маленький crop (<1024px) — масштабируется."""
    result = _upscale_and_encode(small_crop, "test")
    assert len(result) > 0
    import base64, io
    img = Image.open(io.BytesIO(base64.b64decode(result)))
    assert max(img.size) >= 1024


def test_upscale_large_crop(large_crop):
    """Большой crop (>1024px) — не масштабируется."""
    result = _upscale_and_encode(large_crop, "test")
    assert len(result) > 0
    import base64, io
    img = Image.open(io.BytesIO(base64.b64decode(result)))
    assert img.size == (1200, 900)


def test_upscale_nonexistent():
    """Несуществующий файл — ValueError."""
    with pytest.raises(ValueError, match="Не удалось открыть"):
        _upscale_and_encode("/nonexistent/path.png", "test")


def test_upscale_not_image(tmp_path):
    """Файл не изображение — ValueError."""
    bad = tmp_path / "bad.png"
    bad.write_text("не изображение")
    with pytest.raises(ValueError, match="Не удалось открыть"):
        _upscale_and_encode(str(bad), "test")


# === ТЕСТЫ: build_layer2_prompt ===


def test_prompt_kitchen(valid_room, valid_answers):
    """Кухня-гостиная — style, colors, residents в промпте."""
    system, user = build_layer2_prompt(valid_room, valid_answers)
    assert "Кухня-гостиная" in user
    assert "17.7" in user
    assert "Скандинавский" in user


def test_prompt_nan(nan_room, valid_answers):
    """Nan — только базовые вопросы, без hobby/work/bathroom."""
    system, user = build_layer2_prompt(nan_room, valid_answers)
    assert "3.7" in user
    assert "Hobbies" not in user
    assert "Home office" not in user
    assert "Bathroom" not in user


def test_prompt_bathroom(valid_answers):
    """Санузел — вопросы про ванну/душ."""
    room = {"name": "Санузел", "name_source": "context", "area": 3.7, "shape": "прямоугольная"}
    system, user = build_layer2_prompt(room, valid_answers)
    assert "Bath" in user or "Bathroom" in user


# === ТЕСТЫ: generate_room (с моком API) ===


# Минимальный валидный PNG 1x1 px в base64
FAKE_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def test_generate_success(small_crop, valid_room, valid_answers, tmp_path):
    """Полный вызов с моком — файл создаётся."""
    valid_room["crop_path"] = small_crop
    output = str(tmp_path / "refs" / "reference.png")

    fake_msg = {"images": [{"image_url": {"url": f"data:image/png;base64,{FAKE_PNG_B64}"}}]}
    with patch("src.layers.layer2_generate.call_osmi_image", return_value=FAKE_PNG_B64), \
         patch("src.layers.layer2_generate.call_osmi_image_dual", return_value=FAKE_PNG_B64):
        result = generate_room(valid_room, valid_answers, small_crop, output)

    assert result == output
    assert os.path.exists(output)


def test_generate_crop_not_found(valid_room, valid_answers, tmp_path):
    """Crop не существует — FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Crop файл не найден"):
        generate_room(valid_room, valid_answers, "/nonexistent.png", str(tmp_path / "ref.png"))


def test_generate_no_image(small_crop, valid_room, valid_answers, tmp_path):
    """OSMI не вернула изображение — ValueError."""
    valid_room["crop_path"] = small_crop
    with patch("src.layers.layer2_generate.call_osmi_image", side_effect=ValueError("OSMI не вернул изображение")):
        with pytest.raises(ValueError, match="не вернул"):
            generate_room(valid_room, valid_answers, small_crop, str(tmp_path / "ref.png"))
