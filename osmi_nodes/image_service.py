"""
Микросервис обработки изображений для OSMI нод.

Вспомогательный Python-сервис — обрабатывает изображения для OSMI Agent Flow,
потому что в JS-нодах OSMI нет PIL/sharp/jimp. Все операции с пикселями
(апскейл, кроп, поворот, склейка) — здесь.

Эндпоинты:
    POST /upscale        — апскейл изображения x4 с лимитом по длинной стороне
    POST /crop           — кроп комнат по полигонам (блюр/контраст/рамка/зум)
    POST /draw_polygons  — визуализация полигонов на схеме
    POST /rotate         — апскейл + поворот референса (для Слоя 3)
    POST /stitch         — склейка референсов по полигонам (для Слоя 4)
    GET  /health         — проверка доступности

Запуск (локально):
    uvicorn osmi_nodes.image_service:app --port 8000

Прод:
    https://llm-home.fsk.fvds.ru — задеплоен в Docker (Dockerfile + docker-compose.yml в корне репо)
"""

import base64
import io
import os
from typing import Optional

import boto3
from fastapi import FastAPI
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from pydantic import BaseModel


# === КОНФИГУРАЦИЯ ===

# S3 (Yandex Object Storage) — креды обязательны через env (.env файл)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "fsk-service")
S3_PREFIX = os.getenv("S3_PREFIX", "fsk-generate-image")
S3_ACCESS_KEY_ID = os.environ["S3_ACCESS_KEY_ID"]
S3_SECRET_ACCESS_KEY = os.environ["S3_SECRET_ACCESS_KEY"]

# Upscale (Слой 1)
UPSCALE_ZOOM_FACTOR = 4
UPSCALE_MAX_SIDE = 4000

# Crop (Слой 1)
CROP_BLUR_RADIUS = 2
CROP_CONTRAST = 2.5
CROP_SHARPNESS = 1.5
CROP_BORDER_WIDTH = 4
CROP_BORDER_EXPAND = 10
CROP_BORDER_COLOR = "lime"
CROP_PADDING_PCT = 0.15
CROP_ZOOM = 2
CROP_MIN_POLY_SIZE = 5

# Draw polygons (Слой 1)
POLYGON_COLORS = ["red", "blue", "green", "orange", "purple", "cyan", "magenta", "yellow"]
POLYGON_OUTLINE_WIDTH = 5

# Rotate (Слой 3)
REF_MIN_SIZE = 2000

# Stitch (Слой 4)
STITCH_WALL_WIDTH = 4
STITCH_BACKGROUND = (255, 255, 255)


# === S3 КЛИЕНТ ===

_s3_client = None


def get_s3_client():
    """Lazy init S3 клиента — переиспользуется между запросами."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY_ID,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        )
    return _s3_client


def s3_download_image(key: str) -> Image.Image:
    """Скачивает изображение из S3 по ключу."""
    response = get_s3_client().get_object(Bucket=S3_BUCKET, Key=key)
    img_bytes = response["Body"].read()
    return Image.open(io.BytesIO(img_bytes))


def s3_upload_png(img: Image.Image, key: str) -> None:
    """Загружает PIL Image в S3 как PNG."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    get_s3_client().put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buf.getvalue(),
        ContentType="image/png",
    )


# === УТИЛИТЫ ===


def decode_base64_image(b64: str) -> Image.Image:
    """base64 → PIL Image."""
    return Image.open(io.BytesIO(base64.b64decode(b64)))


def encode_image_base64(img: Image.Image, format: str = "PNG") -> str:
    """PIL Image → base64."""
    buf = io.BytesIO()
    img.save(buf, format=format)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def polygon_to_pixels(polygon: list[list[int]], img_w: int, img_h: int) -> list[tuple[int, int]]:
    """Нормализованные координаты 0-1000 → пиксели."""
    return [(int(x / 1000 * img_w), int(y / 1000 * img_h)) for x, y in polygon]


def safe_filename(name: str) -> str:
    """Делает имя безопасным для файловой системы."""
    return name.replace(" ", "_").replace("/", "-")


# === PYDANTIC МОДЕЛИ ===


class RoomPolygon(BaseModel):
    name: str
    polygon: list[list[int]]


# Upscale
class UpscaleRequest(BaseModel):
    image_base64: str
    task_id: str = ""  # если задан → сохраняет в S3, возвращает ключ без base64
    zoom_factor: int = UPSCALE_ZOOM_FACTOR
    max_side: int = UPSCALE_MAX_SIDE


# Crop
class CropRequest(BaseModel):
    image_base64: str = ""
    s3_key: str = ""
    rooms: list[RoomPolygon]


class CropItem(BaseModel):
    name: str
    image_base64: str
    size: list[int]


class CropResponse(BaseModel):
    crops: list[CropItem]


# Draw polygons
class DrawPolygonsRequest(BaseModel):
    s3_key: str
    task_id: str
    rooms: list[RoomPolygon]


# Rotate
class RotateRequest(BaseModel):
    s3_key: str
    task_id: str
    room_name: str
    angle: Optional[int] = None  # None = авто (горизонтальный→90°, вертикальный→0°)
    side: Optional[str] = None   # "a" = авто-угол, "b" = авто+180. Имеет приоритет над angle.


# Stitch
class StitchRoom(BaseModel):
    name: str
    polygon: list[list[int]]
    ref_s3_key: str


class StitchRequest(BaseModel):
    task_id: str
    schema_s3_key: str
    rooms: list[StitchRoom]


# === FASTAPI ===

app = FastAPI(title="FSK Image Service")


# === ЭНДПОИНТЫ ===


@app.post("/upscale")
def upscale(req: UpscaleRequest):
    """Апскейл изображения с лимитом по длинной стороне. Если task_id задан — сохраняет в S3."""
    img = decode_base64_image(req.image_base64)
    orig_w, orig_h = img.size

    # Апскейл
    new_w = orig_w * req.zoom_factor
    new_h = orig_h * req.zoom_factor
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Лимит
    max_side = max(new_w, new_h)
    if max_side > req.max_side:
        scale = req.max_side / max_side
        new_w = int(new_w * scale)
        new_h = int(new_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Если task_id задан — сохраняем в S3, возвращаем только ключ
    if req.task_id:
        s3_key = f"{S3_PREFIX}/{req.task_id}/L1_crops/schema_x2.png"
        s3_upload_png(img, s3_key)
        return {
            "status": "ok",
            "s3_key": s3_key,
            "original_size": [orig_w, orig_h],
            "new_size": [new_w, new_h],
        }

    # Без task_id — возвращаем base64 (обратная совместимость)
    return {
        "image_base64": encode_image_base64(img),
        "original_size": [orig_w, orig_h],
        "new_size": [new_w, new_h],
    }


@app.post("/crop", response_model=CropResponse)
def crop(req: CropRequest):
    """Кроп комнат по полигонам с блюром/контрастом/рамкой/зумом."""
    # Источник: S3 ключ или base64
    if req.s3_key:
        img = s3_download_image(req.s3_key)
    else:
        img = decode_base64_image(req.image_base64)

    img_w, img_h = img.size
    crops = []

    for room in req.rooms:
        polygon = room.polygon
        if len(polygon) < 3:
            continue

        # Координаты в пиксели
        px_points = polygon_to_pixels(polygon, img_w, img_h)
        xs = [p[0] for p in px_points]
        ys = [p[1] for p in px_points]
        poly_w = max(xs) - min(xs)
        poly_h = max(ys) - min(ys)

        if poly_w < CROP_MIN_POLY_SIZE or poly_h < CROP_MIN_POLY_SIZE:
            continue

        # Padding вокруг полигона
        pad_x = int(poly_w * CROP_PADDING_PCT)
        pad_y = int(poly_h * CROP_PADDING_PCT)
        bbox = (
            max(0, min(xs) - pad_x),
            max(0, min(ys) - pad_y),
            min(img_w, max(xs) + pad_x),
            min(img_h, max(ys) + pad_y),
        )

        crop_img = img.crop(bbox)
        local_points = [(px - bbox[0], py - bbox[1]) for px, py in px_points]

        # Расширяем полигон для рамки
        min_x = min(p[0] for p in local_points)
        max_x = max(p[0] for p in local_points)
        min_y = min(p[1] for p in local_points)
        max_y = max(p[1] for p in local_points)
        expanded = []
        for px, py in local_points:
            ex = px - CROP_BORDER_EXPAND if px == min_x else (px + CROP_BORDER_EXPAND if px == max_x else px)
            ey = py - CROP_BORDER_EXPAND if py == min_y else (py + CROP_BORDER_EXPAND if py == max_y else py)
            expanded.append((ex, ey))

        # Маска полигона
        mask = Image.new("L", crop_img.size, 0)
        ImageDraw.Draw(mask).polygon(expanded, fill=255)

        # Контраст внутри, блюр снаружи
        crop_contrast = ImageEnhance.Contrast(crop_img).enhance(CROP_CONTRAST)
        crop_contrast = ImageEnhance.Sharpness(crop_contrast).enhance(CROP_SHARPNESS)
        crop_blurred = crop_img.filter(ImageFilter.GaussianBlur(radius=CROP_BLUR_RADIUS))
        result = Image.composite(crop_contrast, crop_blurred, mask)

        # Зелёная рамка поверх
        ImageDraw.Draw(result).polygon(expanded, outline=CROP_BORDER_COLOR, width=CROP_BORDER_WIDTH)

        # Апскейл кропа
        new_w = result.width * CROP_ZOOM
        new_h = result.height * CROP_ZOOM
        result = result.resize((new_w, new_h), Image.LANCZOS)

        crops.append(CropItem(
            name=room.name,
            image_base64=encode_image_base64(result),
            size=[new_w, new_h],
        ))

    return CropResponse(crops=crops)


@app.post("/draw_polygons")
def draw_polygons(req: DrawPolygonsRequest):
    """Рисует полигоны на схеме и сохраняет в S3 (для отладки Слоя 1)."""
    img = s3_download_image(req.s3_key)
    img_w, img_h = img.size

    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)

    for i, room in enumerate(req.rooms):
        if len(room.polygon) < 3:
            continue

        color = POLYGON_COLORS[i % len(POLYGON_COLORS)]
        px_points = polygon_to_pixels(room.polygon, img_w, img_h)

        # Обводка полигона
        draw.polygon(px_points, outline=color, width=POLYGON_OUTLINE_WIDTH)

        # Подпись по центру
        cx = sum(p[0] for p in px_points) // len(px_points)
        cy = sum(p[1] for p in px_points) // len(px_points)
        draw.text((cx - 20, cy - 10), f"{room.name}", fill=color)

    # Сохраняем в S3
    overlay_key = f"{S3_PREFIX}/{req.task_id}/L1_crops/schema_with_polygons.png"
    s3_upload_png(overlay, overlay_key)

    return {"status": "ok", "s3_key": overlay_key}


@app.post("/rotate")
def rotate(req: RotateRequest):
    """Апскейл до REF_MIN_SIZE + поворот + сохранение в S3 (для Слоя 3)."""
    img = s3_download_image(req.s3_key)
    orig_w, orig_h = img.size

    # Апскейл до REF_MIN_SIZE
    long_side = max(orig_w, orig_h)
    if long_side < REF_MIN_SIZE:
        scale = REF_MIN_SIZE / long_side
        img = img.resize((int(orig_w * scale), int(orig_h * scale)), Image.LANCZOS)

    # Определяем угол поворота
    w, h = img.size
    base_angle = 90 if w > h else 0  # авто по ориентации

    if req.side == "a":
        angle = base_angle
    elif req.side == "b":
        angle = base_angle + 180
    elif req.angle is not None:
        angle = req.angle
    else:
        angle = base_angle

    # Поворот
    if angle != 0:
        img = img.rotate(angle, expand=True, fillcolor=(255, 255, 255))

    # Сохраняем в S3
    safe_name = safe_filename(req.room_name)
    key = f"{S3_PREFIX}/{req.task_id}/L3_renders/{safe_name}_prepared_{angle}deg.png"
    s3_upload_png(img, key)

    return {
        "status": "ok",
        "s3_key": key,
        "angle": angle,
        "size": [img.size[0], img.size[1]],
    }


@app.post("/stitch")
def stitch(req: StitchRequest):
    """Склейка референсов по полигонам + сохранение в S3 (для Слоя 4)."""
    # Скачиваем схему — определяет размер холста
    schema = s3_download_image(req.schema_s3_key)
    w, h = schema.size

    canvas = Image.new("RGB", (w, h), STITCH_BACKGROUND)

    # Вставляем каждый референс по полигону
    for room in req.rooms:
        if len(room.polygon) < 3:
            continue

        # Скачиваем референс
        try:
            ref = s3_download_image(room.ref_s3_key)
        except Exception:
            continue

        # Bbox полигона в пикселях
        px_points = polygon_to_pixels(room.polygon, w, h)
        xs = [p[0] for p in px_points]
        ys = [p[1] for p in px_points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        pw, ph = x_max - x_min, y_max - y_min

        if pw < CROP_MIN_POLY_SIZE or ph < CROP_MIN_POLY_SIZE:
            continue

        # Ресайз референса под полигон
        ref_resized = ref.resize((pw, ph), Image.LANCZOS)

        # Маска по полигону
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(px_points, fill=255)
        mask_crop = mask.crop((x_min, y_min, x_max, y_max))

        canvas.paste(ref_resized, (x_min, y_min), mask_crop)

    # Белые стены поверх
    draw = ImageDraw.Draw(canvas)
    for room in req.rooms:
        if len(room.polygon) < 3:
            continue
        px_points = polygon_to_pixels(room.polygon, w, h)
        draw.polygon(px_points, outline=STITCH_BACKGROUND, width=STITCH_WALL_WIDTH)

    # Сохраняем stitched в S3
    stitched_key = f"{S3_PREFIX}/{req.task_id}/L4_composite/stitched.png"
    s3_upload_png(canvas, stitched_key)

    return {
        "status": "ok",
        "stitched_key": stitched_key,
        "size": [w, h],
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "FSK Image Service"}
