# -*- coding: utf-8 -*-
"""Загрузка тайлов с постоянным кэшем на диске.

Всё, что было скачано хоть раз, остаётся в tiles_cache/ и дальше
используется без обращения к интернету.
"""
import threading

import requests

from .basemaps import SOURCES
from .paths import TILES_CACHE as CACHE_DIR

_session = requests.Session()
_session.headers["User-Agent"] = "dpt-boundary/1.0 (boundary scheme generator)"
_lock = threading.Lock()

TILE_SIZE = 256
# прозрачный тайл-заглушка на случай недоступности источника
_BLANK = None


def _blank_tile() -> bytes:
    global _BLANK
    if _BLANK is None:
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0)).save(buf, "PNG")
        _BLANK = buf.getvalue()
    return _BLANK


def get_tile(source: str, z: int, x: int, y: int) -> bytes:
    """Вернуть PNG-тайл источника, используя дисковый кэш."""
    if source not in SOURCES:
        raise KeyError(source)
    path = CACHE_DIR / source / str(z) / str(x) / f"{y}.png"
    if path.exists():
        return path.read_bytes()
    url = SOURCES[source].format(z=z, x=x, y=y)
    try:
        resp = _session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.content
    except requests.RequestException:
        return _blank_tile()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_bytes(data)
        tmp.replace(path)
    return data
