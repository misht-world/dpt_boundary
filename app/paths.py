# -*- coding: utf-8 -*-
"""Пути к данным и кэшам.

По умолчанию всё лежит в корне проекта (как при запуске на ПК через
run.bat). На сервере задаётся переменная окружения DATA_DIR=/data —
тогда кэши и готовые документы переезжают туда (на постоянный том).
"""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", str(ROOT)))

TILES_CACHE = DATA_DIR / "tiles_cache"
LABELS_CACHE = DATA_DIR / "labels_cache"
OUTPUT_DIR = DATA_DIR / "output"
