"""
Unit-тесты Слоя 2.5: описание артефактов по сторонам.

Тестирует:
    - _parse_artifacts() — парсинг JSON (валидный, markdown, пустой, невалидный)
    - describe_all_sides() — полный вызов с моком API
    - Обработка ошибок (нет референса, ошибка API)

Запуск: pytest tests/layers/test_layer25.py -v
"""

import sys
import os
import json
import pytest
from PIL import Image
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.layers.layer25_describe import _parse_artifacts, describe_all_sides


# === ФИКСТУРЫ ===


@pytest.fixture
def reference_image(tmp_path):
    """Создаёт тестовый референс 800x600 px."""
    img = Image.new("RGB", (800, 600), color="beige")
    path = tmp_path / "reference.png"
    img.save(path)
    return str(path)


@pytest.fixture
def valid_room():
    """Метаданные комнаты."""
    return {"name": "Кухня-гостиная", "area": 17.7, "shape": "прямоугольная"}


# === ТЕСТЫ: _parse_artifacts ===


def test_parse_valid_json():
    """Валидный JSON — парсит артефакты."""
    text = '{"artifacts": [{"name": "диван", "visibility": "full"}, {"name": "стол", "visibility": "partial"}]}'
    result = _parse_artifacts(text, "test")
    assert len(result) == 2
    assert result[0]["name"] == "диван"
    assert result[0]["visibility"] == "full"
    assert result[1]["visibility"] == "partial"


def test_parse_markdown_wrapped():
    """JSON в markdown-обёртке — парсит."""
    text = '```json\n{"artifacts": [{"name": "кровать", "visibility": "full"}]}\n```'
    result = _parse_artifacts(text, "test")
    assert len(result) == 1
    assert result[0]["name"] == "кровать"


def test_parse_empty_response():
    """Пустой ответ — пустой список."""
    result = _parse_artifacts("", "test")
    assert result == []


def test_parse_not_json():
    """Текст не JSON — пустой список (не исключение)."""
    result = _parse_artifacts("Извините, не могу проанализировать", "test")
    assert result == []


def test_parse_no_artifacts_key():
    """JSON без ключа artifacts — пустой список."""
    result = _parse_artifacts('{"items": []}', "test")
    assert result == []


def test_parse_empty_artifacts():
    """Пустой массив artifacts — пустой список."""
    result = _parse_artifacts('{"artifacts": []}', "test")
    assert result == []


# === ТЕСТЫ: describe_all_sides (с моком API) ===


MOCK_API_RESPONSE = '{"artifacts": [{"name": "test item", "visibility": "full"}]}'


def test_describe_all_sides_success(reference_image, valid_room, tmp_path):
    """Полный вызов 4 сторон с моком — возвращает артефакты для каждой."""
    output_dir = str(tmp_path / "artifacts")

    with patch("src.layers.layer25_describe.call_osmi_text", return_value=MOCK_API_RESPONSE):
        result = describe_all_sides(reference_image, valid_room, output_dir)

    # Все 4 стороны
    assert "top" in result
    assert "bottom" in result
    assert "left" in result
    assert "right" in result

    # Каждая сторона имеет артефакты
    for side in ["top", "bottom", "left", "right"]:
        assert len(result[side]) == 1
        assert result[side][0]["name"] == "test item"

    # JSON сохранён
    assert os.path.exists(os.path.join(output_dir, "sides_artifacts.json"))


def test_describe_all_sides_creates_side_images(reference_image, valid_room, tmp_path):
    """Создаёт подготовленные изображения для каждой стороны."""
    output_dir = str(tmp_path / "artifacts")

    with patch("src.layers.layer25_describe.call_osmi_text", return_value=MOCK_API_RESPONSE):
        describe_all_sides(reference_image, valid_room, output_dir)

    # Файлы сторон созданы
    for side in ["top", "bottom", "left", "right"]:
        assert os.path.exists(os.path.join(output_dir, f"side_{side}.png"))


def test_describe_reference_not_found(valid_room, tmp_path):
    """Референс не найден — FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Референс не найден"):
        describe_all_sides("/nonexistent/ref.png", valid_room, str(tmp_path))


def test_describe_api_error_returns_empty(reference_image, valid_room, tmp_path):
    """Ошибка API — пустой список артефактов (не исключение)."""
    output_dir = str(tmp_path / "artifacts")

    with patch("src.layers.layer25_describe.call_osmi_text", side_effect=Exception("API down")):
        result = describe_all_sides(reference_image, valid_room, output_dir)

    # Все стороны пустые — но не падает
    for side in ["top", "bottom", "left", "right"]:
        assert result[side] == []
