# -*- coding: utf-8 -*-
"""Конфигурация подложек.

Каждая подложка — это один или несколько тайловых источников (слоёв),
которые при серверном рендере накладываются друг на друга с заданной
прозрачностью. Клиент (Leaflet) получает те же слои через кэширующий
прокси /tiles/<source>/{z}/{x}/{y}.png
"""

# Тайловые источники: id -> шаблон URL
SOURCES = {
    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "opentopo": "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
    # Генплан СПб 2023 (принятый), слой «Функциональные зоны»
    # рендер NextGIS Web, доступен анонимно
    "gp2023_zones": (
        "https://ecom.nextgis.com/api/component/render/tile"
        "?resource=1921&z={z}&x={x}&y={y}"
    ),
    # Генплан СПб 2023: улично-дорожная сеть (обозначения УДС)
    "gp2023_uds": (
        "https://ecom.nextgis.com/api/component/render/tile"
        "?resource=1953&z={z}&x={x}&y={y}"
    ),
    # Земельные участки Росреестра (ПКК) через NextGIS Geoservices
    # (подключение опубликовано на ecom.nextgis.com, ресурс 691)
    "rr_zu": (
        "https://geoservices.nextgis.com/raster/pkk/ngrr2/{z}/{x}/{y}.png"
        "?apikey=5e90ca928545ce82774a86e6f74ab0ee"
    ),
}

# Подложки, видимые пользователю: список (source_id, opacity)
# Накладываются в порядке перечисления.
BASEMAPS = {
    "osm": {
        "title": "OpenStreetMap",
        "layers": [("osm", 1.0)],
        "max_zoom": 19,
    },
    "gp2023": {
        "title": "Генплан СПб 2023 — функциональные зоны",
        "layers": [("gp2023_zones", 1.0)],
        "max_zoom": 18,
    },
    "gp2023_osm": {
        "title": "Генплан СПб 2023 поверх OSM",
        "layers": [("osm", 1.0), ("gp2023_zones", 0.40)],
        "max_zoom": 18,
    },
    "gp2023_topo": {
        "title": "Генплан СПб 2023 поверх OpenTopoMap",
        "layers": [("opentopo", 1.0), ("gp2023_zones", 0.40)],
        "max_zoom": 17,
    },
    "gp2023_uds": {
        "title": "Генплан СПб 2023 — зоны + УДС",
        "layers": [("gp2023_zones", 1.0), ("gp2023_uds", 1.0)],
        "max_zoom": 18,
    },
    "osm_gp_zu": {
        "title": "OSM + Генплан + ЗУ Росреестра",
        "layers": [("osm", 1.0), ("gp2023_zones", 0.40), ("rr_zu", 1.0)],
        "max_zoom": 18,
    },
    "topo_gp_zu": {
        "title": "OpenTopoMap + Генплан + ЗУ Росреестра",
        "layers": [("opentopo", 1.0), ("gp2023_zones", 0.40), ("rr_zu", 1.0)],
        "max_zoom": 17,
    },
    "osm_zu": {
        "title": "OSM + ЗУ Росреестра",
        "layers": [("osm", 1.0), ("rr_zu", 1.0)],
        "max_zoom": 19,
    },
    "opentopo": {
        "title": "OpenTopoMap (рельеф)",
        "layers": [("opentopo", 1.0)],
        "max_zoom": 17,
    },
}
