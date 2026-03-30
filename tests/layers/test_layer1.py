"""
Unit-тесты Слоя 1: анализ планировки.

Тестирует:
    - _parse_response() — парсинг JSON (чистый, markdown, невалидный, пустой)
    - _validate_response() — pydantic валидация (валидный, без rooms, кривые типы)
    - _crop_rooms() — вырезка (нормальные, clamp, слишком маленькие)

Запуск: pytest tests/layers/test_layer1.py -v
"""

import sys
import os
import json
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.layers.layer1_analyze import _parse_response, _validate_response, _crop_rooms


# === ТЕСТОВЫЕ ДАННЫЕ ===


VALID_RESPONSE = {
    "analysis": "Тестовый анализ: 2 помещения",
    "rooms": [
        {
            "name": "Кухня-гостиная",
            "name_source": "label",
            "area": 17.7,
            "shape": "прямоугольная",
            "analysis": "kitchen with stove and sink",
            "polygon": [[347, 76], [915, 76], [915, 493], [347, 493]],
        },
        {
            "name": "Nan",
            "name_source": "no_label",
            "area": 3.7,
            "shape": "прямоугольная",
            "analysis": "bathroom with toilet",
            "polygon": [[160, 640], [349, 640], [349, 924], [160, 924]],
        },
    ],
}


@pytest.fixture
def tmp_image(tmp_path):
    """Создаёт тестовое изображение 500x400 px."""
    img = Image.new("RGB", (500, 400), color="white")
    path = tmp_path / "test_plan.png"
    img.save(path)
    return str(path)


# === ТЕСТЫ: _parse_response ===


def test_parse_clean_json():
    """Парсит чистый JSON без обёртки."""
    text = json.dumps(VALID_RESPONSE)
    result = _parse_response(text)
    assert result["analysis"] == "Тестовый анализ: 2 помещения"
    assert len(result["rooms"]) == 2


def test_parse_markdown_wrapped():
    """Парсит JSON обёрнутый в ```json...```."""
    text = "```json\n" + json.dumps(VALID_RESPONSE) + "\n```"
    result = _parse_response(text)
    assert len(result["rooms"]) == 2


def test_parse_empty_response():
    """Пустой ответ — ValueError."""
    with pytest.raises(ValueError, match="пустой"):
        _parse_response("")


def test_parse_whitespace():
    """Только пробелы — ValueError."""
    with pytest.raises(ValueError, match="пустой"):
        _parse_response("   \n\t  ")


def test_parse_not_json():
    """Текст не JSON — ValueError с оригинальным текстом."""
    with pytest.raises(ValueError, match="Не удалось распарсить"):
        _parse_response("Извините, я не могу проанализировать это изображение")


# === ТЕСТЫ: _validate_response ===


def test_validate_valid():
    """Валидный ответ проходит."""
    result = _validate_response(VALID_RESPONSE)
    assert len(result.rooms) == 2
    assert result.rooms[0].name == "Кухня-гостиная"
    assert result.rooms[0].area == 17.7


def test_validate_empty_rooms():
    """Пустой rooms — ValueError."""
    with pytest.raises(ValueError, match="не нашла ни одного помещения"):
        _validate_response({"analysis": "Пусто", "rooms": []})


def test_validate_missing_rooms():
    """Нет поля rooms — ValueError."""
    with pytest.raises(ValueError):
        _validate_response({"analysis": "Только анализ"})


def test_validate_negative_area():
    """Отрицательная площадь — ValueError."""
    bad = {"analysis": "T", "rooms": [{"name": "X", "name_source": "label", "area": -5.0, "shape": "п", "polygon": [[0, 0], [500, 0], [500, 500]]}]}
    with pytest.raises(ValueError, match="area должна быть > 0"):
        _validate_response(bad)


def test_validate_bad_polygon():
    """Полигон с менее чем 3 точками — ValueError."""
    bad = {"analysis": "T", "rooms": [{"name": "X", "name_source": "label", "area": 10.0, "shape": "п", "polygon": [[0, 0], [500, 0]]}]}
    with pytest.raises(ValueError, match="at least 3|минимум 3"):
        _validate_response(bad)


def test_validate_bad_name_source():
    """Невалидный name_source — ValueError."""
    bad = {"analysis": "T", "rooms": [{"name": "X", "name_source": "wrong", "area": 10.0, "shape": "п", "polygon": [[0, 0], [500, 0], [500, 500]]}]}
    with pytest.raises(ValueError, match="name_source"):
        _validate_response(bad)


# === ТЕСТЫ: _crop_rooms ===


def test_crop_normal(tmp_image, tmp_path):
    """Нормальная вырезка по полигону — файл создаётся."""
    analysis = {"rooms": [{"name": "Комната", "area": 10.0, "polygon": [[100, 100], [500, 100], [500, 500], [100, 500]]}]}
    result = _crop_rooms(tmp_image, analysis, str(tmp_path / "crops"))
    assert "crop_path" in result["rooms"][0]
    assert os.path.exists(result["rooms"][0]["crop_path"])


def test_crop_too_small(tmp_image, tmp_path):
    """Слишком маленький полигон — пропускается, в skipped."""
    analysis = {"rooms": [{"name": "Tiny", "area": 0.5, "polygon": [[500, 500], [502, 500], [502, 502], [500, 502]]}]}
    result = _crop_rooms(tmp_image, analysis, str(tmp_path / "crops"))
    assert "crop_path" not in result["rooms"][0]
    assert len(result.get("skipped_rooms", [])) == 1


def test_crop_no_polygon(tmp_image, tmp_path):
    """Нет polygon — пропускается."""
    analysis = {"rooms": [{"name": "NoPoly", "area": 10.0}]}
    result = _crop_rooms(tmp_image, analysis, str(tmp_path / "crops"))
    assert "crop_path" not in result["rooms"][0]
    assert len(result.get("skipped_rooms", [])) == 1


def test_crop_multiple(tmp_image, tmp_path):
    """Несколько комнат — каждая вырезается."""
    analysis = {"rooms": [
        {"name": "R1", "area": 10.0, "polygon": [[0, 0], [400, 0], [400, 400], [0, 400]]},
        {"name": "R2", "area": 15.0, "polygon": [[500, 0], [900, 0], [900, 400], [500, 400]]},
        {"name": "R3", "area": 5.0, "polygon": [[0, 500], [400, 500], [400, 900], [0, 900]]},
    ]}
    result = _crop_rooms(tmp_image, analysis, str(tmp_path / "crops"))
    crops = [r for r in result["rooms"] if "crop_path" in r]
    assert len(crops) == 3


def test_crop_irregular(tmp_image, tmp_path):
    """Нестандартный полигон (L-образный) — вырезается."""
    analysis = {"rooms": [{"name": "LRoom", "area": 12.0, "polygon": [
        [100, 100], [500, 100], [500, 300], [300, 300], [300, 500], [100, 500]
    ]}]}
    result = _crop_rooms(tmp_image, analysis, str(tmp_path / "crops"))
    assert "crop_path" in result["rooms"][0]
