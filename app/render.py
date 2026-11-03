# -*- coding: utf-8 -*-
"""Серверный рендер карты: склейка тайлов + граница территории."""
import math
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from .basemaps import BASEMAPS
from .labels import KINDS
from .tiles import TILE_SIZE, get_tile

BOUNDARY_COLOR = (0, 153, 255)  # как в шаблоне, #0099FF
CASING_COLOR = (255, 255, 255)  # белая оконтовка границы
LABEL_COLOR = (40, 40, 40)
TARGET_WIDTH = 1300            # большая сторона картинки, px
                               # (меньше пикселей -> крупнее надписи в печати)
PADDING = 0.18                 # отступ вокруг границы, доля от размера bbox

# доступная область листа под карту (см. docgen), мм
PAGE_IMG_W_MM, PAGE_IMG_H_MM = 165.0, 207.0

# Шрифт для подписей на карте. На ПК — Times New Roman; на Linux-сервере
# его нет, поэтому ищем метрически близкий Liberation Serif (ставится в
# образ), затем DejaVu. Порядок сохраняет прежний вид на ПК.
_FONT_DIRS = [
    "C:/Windows/Fonts",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts",
]
_FONTS = {
    False: ["times.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf",
            "arial.ttf", "DejaVuSans.ttf"],
    True: ["timesbd.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf",
           "arialbd.ttf", "DejaVuSans-Bold.ttf"],
}


def _load_font(size: int, bold: bool):
    for directory in _FONT_DIRS:
        for name in _FONTS[bold]:
            try:
                return ImageFont.truetype(f"{directory}/{name}", size)
            except OSError:
                continue
    return ImageFont.load_default()


def _lonlat_to_global_px(lon: float, lat: float, z: int):
    """Долгота/широта -> глобальные пиксельные координаты Web Mercator."""
    n = 2 ** z * TILE_SIZE
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _world_to_lonlat(x: float, y: float):
    """Обратное преобразование мировых координат (зум 0) в WGS84."""
    lon = x / TILE_SIZE * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / TILE_SIZE))))
    return lon, lat


def padded_bbox(coords):
    """Рамка кадра с отступами: (min_lon, min_lat, max_lon, max_lat)."""
    xs, ys = zip(*(_lonlat_to_global_px(lon, lat, 0) for lon, lat in coords))
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    pad = max(x2 - x1, y2 - y1, 1e-7) * PADDING
    x1, x2, y1, y2 = x1 - pad, x2 + pad, y1 - pad, y2 + pad
    min_lon, max_lat = _world_to_lonlat(x1, y1)
    max_lon, min_lat = _world_to_lonlat(x2, y2)
    return min_lon, min_lat, max_lon, max_lat


def render_map(coords, basemap_id: str, labels=None, label_scale: float = 1.0,
               frame=None, north_arrow: bool = True):
    """coords: [(lon, lat), ...] замкнутого контура (WGS84).

    labels: [{name, lat, lon, angle, kind}] — надписи поверх карты.
    frame: (min_lon, min_lat, max_lon, max_lat) — своя рамка кадра
           (если не задана — рассчитывается от контура с отступами).
    Возвращает (Image, толщина линии границы в px).
    """
    bm = BASEMAPS[basemap_id]

    if frame:
        fx1, fy1 = _lonlat_to_global_px(frame[0], frame[3], 0)
        fx2, fy2 = _lonlat_to_global_px(frame[2], frame[1], 0)
        x1, x2 = min(fx1, fx2), max(fx1, fx2)
        y1, y2 = min(fy1, fy2), max(fy1, fy2)
    else:
        # bbox в мировых координатах (зум 0), паддинг от большей стороны
        xs, ys = zip(*(_lonlat_to_global_px(lon, lat, 0) for lon, lat in coords))
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        pad = max(x2 - x1, y2 - y1, 1e-7) * PADDING
        x1, x2, y1, y2 = x1 - pad, x2 + pad, y1 - pad, y2 + pad

    # подбор зума: большая сторона картинки ближе всего к TARGET_WIDTH
    world = max(x2 - x1, y2 - y1)
    zoom = min(
        range(4, bm["max_zoom"] + 1),
        key=lambda z: abs(math.log(world * 2 ** z / TARGET_WIDTH)),
    )

    scale = 2 ** zoom
    px1, py1, px2, py2 = x1 * scale, y1 * scale, x2 * scale, y2 * scale
    tx1, ty1 = int(px1 // TILE_SIZE), int(py1 // TILE_SIZE)
    tx2, ty2 = int(px2 // TILE_SIZE), int(py2 // TILE_SIZE)

    w = (tx2 - tx1 + 1) * TILE_SIZE
    h = (ty2 - ty1 + 1) * TILE_SIZE
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))

    # параллельная догрузка всех тайлов всех слоёв
    jobs = [
        (src, zoom, x, y)
        for src, _ in bm["layers"]
        for x in range(tx1, tx2 + 1)
        for y in range(ty1, ty2 + 1)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        tiles = dict(
            zip(jobs, pool.map(lambda j: get_tile(*j), jobs))
        )

    for src, opacity in bm["layers"]:
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for x in range(tx1, tx2 + 1):
            for y in range(ty1, ty2 + 1):
                tile = Image.open(BytesIO(tiles[(src, zoom, x, y)])).convert("RGBA")
                layer.paste(tile, ((x - tx1) * TILE_SIZE, (y - ty1) * TILE_SIZE))
        if opacity < 1.0:
            alpha = layer.getchannel("A").point(lambda a: int(a * opacity))
            layer.putalpha(alpha)
        canvas = Image.alpha_composite(canvas, layer)

    # обрезка до bbox
    ox, oy = tx1 * TILE_SIZE, ty1 * TILE_SIZE
    crop = (
        int(px1 - ox), int(py1 - oy),
        int(px2 - ox), int(py2 - oy),
    )
    canvas = canvas.crop(crop)

    # граница
    draw = ImageDraw.Draw(canvas)
    pts = []
    for lon, lat in coords:
        gx, gy = _lonlat_to_global_px(lon, lat, zoom)
        pts.append((gx - ox - crop[0], gy - oy - crop[1]))
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    line_w = max(6, max(canvas.width, canvas.height) // 160)
    casing_w = line_w + max(4, line_w // 2)
    draw.line(pts, fill=CASING_COLOR, width=casing_w, joint="curve")
    for p in pts:  # скругление стыков оконтовки
        r = casing_w / 2
        draw.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=CASING_COLOR)
    draw.line(pts, fill=BOUNDARY_COLOR, width=line_w, joint="curve")
    for p in pts:
        r = line_w / 2
        draw.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=BOUNDARY_COLOR)

    # масштаб вставки картинки на лист (см. docgen)
    aspect = canvas.height / canvas.width
    disp_w_mm = min(PAGE_IMG_W_MM, PAGE_IMG_H_MM / aspect)
    px_per_mm = canvas.width / disp_w_mm

    # надписи
    if labels:
        canvas = _draw_labels(canvas, labels, zoom, ox + crop[0], oy + crop[1],
                              px_per_mm, label_scale)

    if north_arrow:
        _draw_north_arrow(canvas, px_per_mm)

    return canvas.convert("RGB"), line_w


def _draw_north_arrow(canvas, px_per_mm):
    """Значок севера в правом верхнем углу (стрелка + «С»)."""
    d = ImageDraw.Draw(canvas)
    mm = px_per_mm
    margin = 4 * mm
    cx = canvas.width - margin - 5 * mm  # ось значка
    letter_size = int(5 * mm)
    font = _load_font(letter_size, True)
    stroke = max(2, letter_size // 6)
    # буква «С»
    d.text((cx, margin + 2.5 * mm), "С", font=font, fill=LABEL_COLOR,
           stroke_width=stroke, stroke_fill=(255, 255, 255), anchor="mm")
    # стрелка: две половинки треугольника
    top = margin + 5.5 * mm
    bot = top + 8 * mm
    w = 2.6 * mm
    notch = bot - 2 * mm  # выемка снизу
    left = [(cx, top), (cx - w, bot), (cx, notch)]
    right = [(cx, top), (cx + w, bot), (cx, notch)]
    d.polygon(left + [left[0]], outline=(255, 255, 255),
              width=max(2, int(0.4 * mm)))
    d.polygon(right + [right[0]], outline=(255, 255, 255),
              width=max(2, int(0.4 * mm)))
    d.polygon(left, fill=LABEL_COLOR)
    d.polygon(right, fill=(255, 255, 255), outline=LABEL_COLOR,
              width=max(1, int(0.25 * mm)))


def _draw_labels(canvas, labels, zoom, off_x, off_y, px_per_mm, scale=1.0):
    """Рисует надписи; размер шрифта в мм на листе пересчитывается в px."""
    for lab in labels:
        kind = KINDS.get(lab.get("kind"))
        if not kind:
            continue
        text = lab["name"]
        if kind["caps"]:
            text = text.upper()
        size = max(8, round(kind["mm"] * scale * px_per_mm))
        font = _load_font(size, kind["bold"])
        stroke = max(2, size // 6)

        gx, gy = _lonlat_to_global_px(lab["lon"], lab["lat"], zoom)
        cx, cy = gx - off_x, gy - off_y
        angle = float(lab.get("angle") or 0)

        # текст на прозрачном слое -> поворот -> наложение по центру
        tmp_d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bb = tmp_d.textbbox((0, 0), text, font=font, stroke_width=stroke)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        tile = Image.new("RGBA", (tw + 2 * stroke, th + 2 * stroke), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        d.text((stroke - bb[0], stroke - bb[1]), text, font=font,
               fill=LABEL_COLOR, stroke_width=stroke,
               stroke_fill=(255, 255, 255))
        if angle:
            tile = tile.rotate(angle, expand=True, resample=Image.BICUBIC)
        canvas.alpha_composite(
            tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))
    return canvas
