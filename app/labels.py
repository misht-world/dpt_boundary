# -*- coding: utf-8 -*-
"""Надписи для схемы: названия улиц, населённых пунктов, МО и районов.

Данные берутся из OSM через Overpass API и кэшируются на диск.
Расстановка: улицы — вдоль самого длинного участка в кадре,
точечные объекты — по координате; всё можно двигать в веб-интерфейсе.
"""
import hashlib
import json
import math
import pathlib

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "labels_cache"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
_HEADERS = {"User-Agent": "dpt-boundary/1.0 (boundary scheme generator)"}

# виды надписей: (приоритет, высота шрифта в мм на листе)
KINDS = {
    "street": {"title": "Улицы", "mm": 6.6, "bold": False, "caps": False},
    "place": {"title": "Населённые пункты", "mm": 6.0, "bold": True, "caps": False},
    "mo": {"title": "Муниципальные образования", "mm": 3.2, "bold": True, "caps": False},
    "district": {"title": "Районы", "mm": 3.8, "bold": True, "caps": True},
}


def _overpass(query: str) -> dict:
    key = hashlib.md5(query.encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    last_err = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query},
                                 headers=_HEADERS, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException as e:
            last_err = e
    else:
        raise last_err
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _merc(lon, lat):
    """Псевдо-Меркатор для расчёта углов/длин (безразмерный)."""
    x = lon / 360.0
    y = -math.asinh(math.tan(math.radians(lat))) / (2 * math.pi)
    return x, y


def get_labels(bbox, kinds):
    """bbox = (min_lon, min_lat, max_lon, max_lat); kinds — набор из KINDS.

    Возвращает [{name, lat, lon, angle, kind}] — angle в градусах
    (0 = горизонтально, против часовой), для точечных объектов 0.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    bb = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    labels = []

    if "street" in kinds:
        q = (f'[out:json][timeout:90];way["highway"]["name"]({bb});'
             "out geom;")
        data = _overpass(q)
        streets = {}
        for el in data.get("elements", []):
            name = el.get("tags", {}).get("name")
            geom = el.get("geometry") or []
            if not name or len(geom) < 2:
                continue
            streets.setdefault(name, []).append(geom)
        for name, ways in streets.items():
            best = _best_segment(ways, bbox)
            if best:
                lat, lon, angle = best
                labels.append({"name": name, "lat": lat, "lon": lon,
                               "angle": angle, "kind": "street"})

    if "place" in kinds:
        q = (f'[out:json][timeout:90];'
             f'node["place"~"^(city|town|village|hamlet|suburb|'
             f'neighbourhood|quarter)$"]["name"]({bb});out;')
        for el in _overpass(q).get("elements", []):
            name = el.get("tags", {}).get("name")
            if name:
                labels.append({"name": name, "lat": el["lat"], "lon": el["lon"],
                               "angle": 0, "kind": "place"})

    for kind, level in (("district", "5"), ("mo", "8")):
        if kind not in kinds:
            continue
        q = (f'[out:json][timeout:90];'
             f'relation["boundary"="administrative"]'
             f'["admin_level"="{level}"]["name"]({bb});out center;')
        for el in _overpass(q).get("elements", []):
            name = el.get("tags", {}).get("name")
            c = el.get("center")
            if not name or not c:
                continue
            # центр МО может лежать за кадром — тогда прижимаем к кадру
            lat = min(max(c["lat"], min_lat), max_lat)
            lon = min(max(c["lon"], min_lon), max_lon)
            labels.append({"name": name, "lat": lat, "lon": lon,
                           "angle": 0, "kind": kind})

    return labels


def _best_segment(ways, bbox):
    """Середина и угол самого длинного куска улицы внутри кадра."""
    min_lon, min_lat, max_lon, max_lat = bbox
    best_len, best = 0.0, None
    for geom in ways:
        pts = [(g["lon"], g["lat"]) for g in geom
               if min_lon <= g["lon"] <= max_lon and min_lat <= g["lat"] <= max_lat]
        if len(pts) < 2:
            continue
        m = [_merc(lon, lat) for lon, lat in pts]
        total = sum(math.dist(m[i], m[i + 1]) for i in range(len(m) - 1))
        if total <= best_len:
            continue
        # точка на середине полилинии и угол сегмента в ней
        half, acc = total / 2, 0.0
        for i in range(len(m) - 1):
            seg = math.dist(m[i], m[i + 1])
            if acc + seg >= half and seg > 0:
                t = (half - acc) / seg
                lon = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
                lat = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
                dx = m[i + 1][0] - m[i][0]
                dy = m[i + 1][1] - m[i][1]
                angle = -math.degrees(math.atan2(dy, dx))
                if angle > 90:
                    angle -= 180
                elif angle < -90:
                    angle += 180
                best_len, best = total, (lat, lon, round(angle, 1))
                break
            acc += seg
    return best
