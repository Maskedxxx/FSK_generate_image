"""
Pydantic-модели для валидации данных между слоями.

Модели:
    RoomAnalysis    — одно помещение из Слоя 1
    FloorplanResult — полный результат Слоя 1 (analysis + rooms)
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class RoomAnalysis(BaseModel):
    """
    Одно помещение из результата Слоя 1.

    Поля:
        name — текстовая подпись или функция комнаты (kitchen, bathroom, hallway, Nan)
        name_source — "label" (подпись есть) или "no_label" (только метраж)
        area — площадь в м²
        shape — геометрическая форма
        analysis — рассуждения модели по этой комнате
        polygon — координаты полигона [[x,y], ...] нормализованные 0-1000
        crop_path — путь к вырезанному изображению (заполняется после crop)
    """
    name: str
    name_source: str
    area: float
    shape: str
    analysis: str = ""
    polygon: list[list[int]] = Field(min_length=3)
    crop_path: Optional[str] = None

    @field_validator("name_source")
    @classmethod
    def validate_name_source(cls, v: str) -> str:
        """Проверяет что name_source — допустимое значение."""
        if v not in ("label", "no_label"):
            raise ValueError(f"name_source должен быть 'label' или 'no_label', получен: '{v}'")
        return v

    @field_validator("area", mode="before")
    @classmethod
    def validate_area(cls, v) -> float:
        """
        Парсит площадь — обрабатывает русский формат (запятая вместо точки).
        Примеры: 17.7, "17,7", "3,4 (1,7)" → берёт первое число.
        """
        if isinstance(v, str):
            v = v.split("(")[0].strip()
            v = v.replace(",", ".")
            v = float(v)
        if v <= 0:
            raise ValueError(f"area должна быть > 0, получено: {v}")
        return v

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, v: list[list[int]]) -> list[list[int]]:
        """Проверяет что полигон имеет минимум 3 точки и каждая точка [x, y]."""
        if len(v) < 3:
            raise ValueError(f"polygon должен иметь минимум 3 точки, получено: {len(v)}")
        for i, point in enumerate(v):
            if len(point) != 2:
                raise ValueError(f"polygon точка {i} должна быть [x, y], получено: {point}")
        return v


class FloorplanResult(BaseModel):
    """
    Полный результат Слоя 1 — анализ планировки.

    Поля:
        analysis — общие рассуждения модели (текст)
        rooms — список помещений
    """
    analysis: str
    rooms: list[RoomAnalysis]

    @field_validator("rooms")
    @classmethod
    def validate_rooms_not_empty(cls, v: list[RoomAnalysis]) -> list[RoomAnalysis]:
        """Проверяет что найдено хотя бы одно помещение."""
        if len(v) == 0:
            raise ValueError("Модель не нашла ни одного помещения на схеме")
        return v
