"""
Unit-тесты osmi_client — клиент для вызова OSMI-нод.

Тестирует:
    - _extract_image_from_markdown() — извлечение base64 из markdown
    - Обработка ошибок (нет изображения, неверный формат)

Запуск: pytest tests/test_osmi_client.py -v
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.osmi_client import _extract_image_from_markdown


FAKE_B64 = "iVBORw0KGgo="


def test_extract_png():
    """Markdown с PNG — извлекает base64."""
    text = f"![Generated Image](data:image/png;base64,{FAKE_B64})"
    assert _extract_image_from_markdown(text, "test") == FAKE_B64


def test_extract_jpeg():
    """Markdown с JPEG — извлекает base64."""
    text = f"![Generated Image](data:image/jpeg;base64,{FAKE_B64})"
    assert _extract_image_from_markdown(text, "test") == FAKE_B64


def test_no_image_in_response():
    """Текст без изображения — ValueError."""
    with pytest.raises(ValueError, match="не вернул изображение"):
        _extract_image_from_markdown("Просто текст без картинки", "test")


def test_empty_response():
    """Пустой ответ — ValueError."""
    with pytest.raises(ValueError, match="не вернул изображение"):
        _extract_image_from_markdown("", "test")


def test_bad_url_format():
    """URL не data: — ValueError."""
    text = "![Image](https://example.com/img.png)"
    with pytest.raises(ValueError, match="Неожиданный формат"):
        _extract_image_from_markdown(text, "test")


def test_text_with_image():
    """Текст + изображение — извлекает base64."""
    text = f"Вот результат: ![Room](data:image/png;base64,{FAKE_B64})"
    assert _extract_image_from_markdown(text, "test") == FAKE_B64
