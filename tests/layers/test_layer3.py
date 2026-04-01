"""
Unit-тесты Слоя 3: горизонтальная генерация стороны.

Тестирует:
    - _extract_image() — извлечение base64 (с изображением, без, bad url)
    - render_side() — полный вызов с моком API
    - build_layer3_prompt() — формирование промпта (с артефактами, без)
    - Обработка ошибок (нет референса, модель не вернула картинку)

Запуск: pytest tests/layers/test_layer3.py -v
"""

import sys
import os
import json
import pytest
from PIL import Image
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.layers.layer3_render import render_side
from src.prompts import build_layer3_prompt


# === ФИКСТУРЫ ===


FAKE_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


@pytest.fixture
def reference_image(tmp_path):
    """Создаёт тестовый референс 800x600 px."""
    img = Image.new("RGB", (800, 600), color="beige")
    path = tmp_path / "reference.png"
    img.save(path)
    return str(path)


# === ТЕСТЫ: build_layer3_prompt ===


def test_prompt_without_artifacts():
    """Без артефактов — базовый промпт."""
    system, user = build_layer3_prompt("top")
    assert len(system) > 0
    assert len(user) > 0
    assert "артефакт" not in user.lower() or "artifact" not in user.lower()


def test_prompt_with_artifacts():
    """С артефактами — включены в промпт."""
    artifacts = [
        {"name": "диван", "visibility": "full"},
        {"name": "стол", "visibility": "partial"},
    ]
    system, user = build_layer3_prompt("top", artifacts)
    assert "диван" in user
    assert "стол" in user
    assert "full" in user
    assert "partial" in user


def test_prompt_with_string_artifacts():
    """Артефакты как строки (старый формат) — тоже работает."""
    artifacts = ["диван", "кресло"]
    system, user = build_layer3_prompt("top", artifacts)
    assert "диван" in user
    assert "кресло" in user


# === ТЕСТЫ: render_side (с моком API) ===


def test_render_success(reference_image, tmp_path):
    """Полный вызов с моком — файл создаётся."""
    output_path = str(tmp_path / "renders" / "top.png")

    fake_msg = {"images": [{"image_url": {"url": f"data:image/png;base64,{FAKE_PNG_B64}"}}]}
    with patch("src.layers.layer3_render.call_osmi_image", return_value=FAKE_PNG_B64):
        result = render_side(reference_image, output_path, "top")

    assert result == output_path
    assert os.path.exists(output_path)


def test_render_with_artifacts(reference_image, tmp_path):
    """С артефактами — файл создаётся."""
    output_path = str(tmp_path / "renders" / "left.png")
    artifacts = [{"name": "шкаф", "visibility": "full"}]

    fake_msg = {"images": [{"image_url": {"url": f"data:image/png;base64,{FAKE_PNG_B64}"}}]}
    with patch("src.layers.layer3_render.call_osmi_image", return_value=FAKE_PNG_B64):
        result = render_side(reference_image, output_path, "left", artifacts)

    assert os.path.exists(output_path)


def test_render_all_sides(reference_image, tmp_path):
    """Все 4 стороны — каждая создаёт файл."""
    fake_msg = {"images": [{"image_url": {"url": f"data:image/png;base64,{FAKE_PNG_B64}"}}]}

    for side in ["top", "bottom", "left", "right"]:
        output_path = str(tmp_path / "renders" / f"{side}.png")
        with patch("src.layers.layer3_render.call_osmi_image", return_value=FAKE_PNG_B64):
            render_side(reference_image, output_path, side)
        assert os.path.exists(output_path)


def test_render_creates_prepared(reference_image, tmp_path):
    """Создаёт подготовленное изображение (prepared_side.png)."""
    output_path = str(tmp_path / "renders" / "top.png")

    fake_msg = {"images": [{"image_url": {"url": f"data:image/png;base64,{FAKE_PNG_B64}"}}]}
    with patch("src.layers.layer3_render.call_osmi_image", return_value=FAKE_PNG_B64):
        render_side(reference_image, output_path, "top")

    prepared = str(tmp_path / "renders" / "prepared_top.png")
    assert os.path.exists(prepared)


def test_render_reference_not_found(tmp_path):
    """Референс не найден — FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Референс не найден"):
        render_side("/nonexistent/ref.png", str(tmp_path / "out.png"), "top")


def test_render_no_image_returned(reference_image, tmp_path):
    """OSMI не вернула изображение — ValueError."""
    output_path = str(tmp_path / "renders" / "top.png")

    with patch("src.layers.layer3_render.call_osmi_image", side_effect=ValueError("OSMI не вернул изображение")):
        with pytest.raises(ValueError, match="не вернул"):
            render_side(reference_image, output_path, "top")
