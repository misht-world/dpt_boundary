# -*- coding: utf-8 -*-
"""Импорт границы из DXF в местной системе координат.

Официальные параметры МСК-64 СПб закрыты; используются общепринятые
открытые наборы (точность порядка метра — для ориентировочных границ
достаточно). DWG предварительно сконвертировать в DXF
(например, бесплатным ODA File Converter).
"""
import io
import math

from ezdxf import recover
from pyproj import Transformer

# Системы координат чертежа. proj-строки — открытые параметры.
CRS = {
    "msk64_gost": {
        "title": "МСК-64 СПб (ГОСТ 51794-2008)",
        "proj": ("+proj=tmerc +lat_0=0 +lon_0=30 +k=1 "
                 "+x_0=95942.17 +y_0=-6552810.0 +ellps=krass "
                 "+towgs84=23.57,-140.95,-79.8,0,0.35,0.79,-0.22 "
                 "+units=m +no_defs"),
    },
    "msk64_calc": {
        "title": "МСК-64 СПб (расчётный вариант)",
        "proj": ("+proj=tmerc +lat_0=0 +lon_0=30 +k=1 "
                 "+x_0=95948.85 +y_0=-6552807.1 +ellps=krass "
                 "+towgs84=24,-123,-94,0.02,-0.25,-0.13,1.1 "
                 "+units=m +no_defs"),
    },
    "wgs84": {
        "title": "WGS84 (градусы, X=долгота)",
        "proj": "+proj=longlat +datum=WGS84 +no_defs",
    },
}

# рамка правдоподобия результата (СПб и окрестности)
_SPB = (28.0, 58.5, 32.5, 61.5)  # min_lon, min_lat, max_lon, max_lat


def _polylines_from_dxf(data: bytes):
    """Все полилинии из modelspace: [(points, closed)], points=[(x, y)]."""
    doc, _auditor = recover.read(io.BytesIO(data))
    msp = doc.modelspace()
    result = []
    for e in msp:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
            result.append((pts, bool(e.closed)))
        elif t == "POLYLINE" and not e.is_3d_polyline:
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            result.append((pts, bool(e.is_closed)))
        elif t == "LINE":
            result.append((
                [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)],
                False,
            ))
    return [(pts, closed) for pts, closed in result if len(pts) >= 2]


def _area(pts):
    return abs(sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1]
        - pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )) / 2


def _inside_spb(lonlat):
    lon, lat = lonlat
    return (_SPB[0] <= lon <= _SPB[2] and _SPB[1] <= lat <= _SPB[3])


def import_dxf(data: bytes, crs_id: str, axes: str = "auto"):
    """Возвращает (контур [(lon, lat), ...], сообщение).

    axes: "xy" — X чертежа = восток (математические оси),
          "yx" — X чертежа = север (геодезические оси),
          "auto" — подобрать по попаданию в окрестности СПб.
    """
    if crs_id not in CRS:
        raise ValueError("Неизвестная система координат")
    polys = _polylines_from_dxf(data)
    if not polys:
        raise ValueError("В DXF не найдено полилиний")

    # лучший кандидат: замкнутая полилиния наибольшей площади,
    # иначе — самая длинная полилиния
    closed = [(pts, c) for pts, c in polys if c or
              (len(pts) > 3 and math.dist(pts[0], pts[-1]) < 0.01)]
    if closed:
        pts = max((p for p, _ in closed), key=_area)
        note = f"замкнутых контуров: {len(closed)}, взят наибольший"
    else:
        pts = max((p for p, _ in polys),
                  key=lambda p: sum(math.dist(p[i], p[i + 1])
                                    for i in range(len(p) - 1)))
        note = "замкнутых контуров нет, взята самая длинная полилиния"

    tr = Transformer.from_crs(CRS[crs_id]["proj"], "EPSG:4326",
                              always_xy=True)

    # порядок осей: в геодезических чертежах часто X=север, Y=восток
    direct = [tr.transform(x, y) for x, y in pts]
    swapped = [tr.transform(y, x) for x, y in pts]
    ok_direct = all(map(_inside_spb, direct))
    ok_swapped = all(map(_inside_spb, swapped))
    if axes == "xy":
        lonlat = direct
    elif axes == "yx":
        lonlat = swapped
    elif ok_direct and ok_swapped:
        # оба варианта правдоподобны — сами угадать нельзя
        lonlat = direct
        note += ("; ВНИМАНИЕ: ориентация осей неоднозначна — если контур "
                 "лёг не на то место, выберите порядок осей вручную")
    elif ok_direct:
        lonlat = direct
    elif ok_swapped:
        lonlat = swapped
        note += "; оси X/Y переставлены автоматически"
    else:
        raise ValueError(
            "Координаты не похожи на выбранную систему: результат вне "
            "окрестностей Санкт-Петербурга. Проверьте систему координат.")

    if len(lonlat) > 1 and lonlat[0] == lonlat[-1]:
        lonlat = lonlat[:-1]
    return lonlat, f"Точек: {len(lonlat)} ({note})"
