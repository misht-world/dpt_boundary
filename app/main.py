# -*- coding: utf-8 -*-
"""Схемы границ территорий — локальное веб-приложение.

Запуск:  python -m uvicorn app.main:app --port 8077
или run.bat в корне проекта.
"""
import datetime
import os
import pathlib
import re
import sys
import time
from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from pyproj import Geod
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth
from .basemaps import BASEMAPS
from .docgen import build_docx
from .dxf_import import CRS, import_dxf
from .labels import KINDS, get_labels
from .paths import OUTPUT_DIR
from .render import padded_bbox, render_map
from .tiles import get_tile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Готовые документы одноразовые: чистим всё старше часа при каждой генерации.
OUTPUT_TTL_SECONDS = 3600

app = FastAPI(title="dpt_boundary")
auth.install(app)


def _sweep_output() -> None:
    """Удаляет .docx старше OUTPUT_TTL_SECONDS, чтобы диск не рос."""
    deadline = time.time() - OUTPUT_TTL_SECONDS
    try:
        for p in OUTPUT_DIR.glob("*.docx"):
            try:
                if p.stat().st_mtime < deadline:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass


@app.get("/api/basemaps")
def api_basemaps():
    return [
        {
            "id": bid,
            "title": bm["title"],
            "layers": [
                {"url": f"/tiles/{src}/{{z}}/{{x}}/{{y}}.png", "opacity": op}
                for src, op in bm["layers"]
            ],
            "max_zoom": bm["max_zoom"],
        }
        for bid, bm in BASEMAPS.items()
    ]


@app.get("/tiles/{source}/{z}/{x}/{y}.png")
def api_tile(source: str, z: int, x: int, y: int):
    try:
        data = get_tile(source, z, x, y)
    except KeyError:
        raise HTTPException(404, "unknown source")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


class LabelItem(BaseModel):
    name: str
    lat: float
    lon: float
    angle: float = 0
    kind: str


_geod = Geod(ellps="WGS84")


def _metric_text(coords, object_type: str) -> str:
    """«Ориентировочная площадь/протяжённость» по контуру."""
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    if object_type == "areal":
        area, _ = _geod.polygon_area_perimeter(lons, lats)
        ha = abs(area) / 10000.0
        val = f"{ha:.1f}".replace(".", ",")
        return f"Ориентировочная площадь — {val} га"
    if object_type == "linear":
        n = len(coords)
        best = 0.0
        for i in range(n):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[(i + 1) % n]
            _, _, dist = _geod.inv(lon1, lat1, lon2, lat2)
            best = max(best, dist)
        km = best / 1000.0
        val = f"{km:.1f}".replace(".", ",")
        return f"Ориентировочная протяжённость — {val} км"
    return ""


class LabelsRequest(BaseModel):
    coords: list[list[float]]  # контур границы [[lon, lat], ...]
    kinds: list[str]
    frame: list[float] | None = None  # своя рамка (min_lon, min_lat, max_lon, max_lat)


@app.get("/api/label_kinds")
def api_label_kinds():
    return [{"id": k, "title": v["title"], "mm": v["mm"],
             "bold": v["bold"], "caps": v["caps"]}
            for k, v in KINDS.items()]


@app.post("/api/labels")
def api_labels(req: LabelsRequest):
    if len(req.coords) < 3:
        raise HTTPException(400, "Нужно минимум 3 точки границы")
    if req.frame and len(req.frame) == 4:
        bbox = tuple(req.frame)
    else:
        bbox = padded_bbox([(c[0], c[1]) for c in req.coords])
    try:
        return get_labels(bbox, set(req.kinds))
    except Exception as e:  # Overpass недоступен и т.п.
        raise HTTPException(502, f"Не удалось получить надписи: {e}")


@app.get("/api/dxf_crs")
def api_dxf_crs():
    return [{"id": k, "title": v["title"]} for k, v in CRS.items()]


@app.post("/api/import_dxf")
async def api_import_dxf(file: UploadFile = File(...), crs: str = Form(...),
                         axes: str = Form("auto")):
    if file.filename and file.filename.lower().endswith(".dwg"):
        raise HTTPException(
            400, "DWG не поддерживается напрямую — сохраните чертёж как DXF "
                 "(или сконвертируйте бесплатным ODA File Converter)")
    data = await file.read()
    try:
        coords, note = import_dxf(data, crs, axes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать DXF: {e}")
    return {"coords": [[lon, lat] for lon, lat in coords], "note": note}


class GenerateRequest(BaseModel):
    coords: list[list[float]]  # [[lon, lat], ...]
    basemap: str
    territory: str = ""
    annex_no: str = ""
    open_word: bool = True
    labels: list[LabelItem] = []
    label_scale: float = 1.0
    object_type: str = "linear"  # linear | areal | none
    north_arrow: bool = True
    frame: list[float] | None = None  # своя рамка кадра


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    if len(req.coords) < 3:
        raise HTTPException(400, "Нужно минимум 3 точки границы")
    if req.basemap not in BASEMAPS:
        raise HTTPException(400, "Неизвестная подложка")

    coords = [(c[0], c[1]) for c in req.coords]
    frame = tuple(req.frame) if req.frame and len(req.frame) == 4 else None
    img, line_px = render_map(
        coords, req.basemap,
        labels=[l.model_dump() for l in req.labels],
        label_scale=req.label_scale,
        frame=frame, north_arrow=req.north_arrow)
    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)

    _sweep_output()
    safe = re.sub(r'[\\/:*?"<>|]+', "_", req.territory).strip() or "схема"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = OUTPUT_DIR / f"Приложение - {safe[:80]} {stamp}.docx"
    build_docx(buf, req.territory, req.annex_no, out, line_px=line_px,
               metric_text=_metric_text(coords, req.object_type))

    # «Открыть в Word» — только на ПК; на сервере (Linux) Word нет,
    # документ скачивается по ссылке /api/download.
    if req.open_word and sys.platform == "win32":
        try:
            os.startfile(str(out))  # откроет в Word
        except OSError:
            pass

    return {"file": out.name, "path": str(out)}


@app.get("/api/download/{name}")
def api_download(name: str):
    path = OUTPUT_DIR / name
    if not path.is_file() or path.parent != OUTPUT_DIR:
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        filename=name,
    )


app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True),
          name="static")
