# -*- coding: utf-8 -*-
"""Формирование Word-документа по образцу из template/."""
import pathlib
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

ROOT = pathlib.Path(__file__).resolve().parent.parent

FONT = "Times New Roman"

BOUNDARY_COLOR = (0, 153, 255)  # #0099FF, как на карте
SWATCH_W_MM, SWATCH_H_MM = 32.0, 13.0  # размер знака в легенде
SWATCH_SCALE = 12  # px на мм при отрисовке знака


def _make_swatch(line_mm: float) -> BytesIO:
    """Прямоугольник-знак с толщиной линии как у границы на схеме (в мм)."""
    from PIL import Image, ImageDraw

    w = int(SWATCH_W_MM * SWATCH_SCALE)
    h = int(SWATCH_H_MM * SWATCH_SCALE)
    t = max(2, round(line_mm * SWATCH_SCALE))
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    half = t // 2
    d.rectangle((half, half, w - 1 - half, h - 1 - half),
                outline=BOUNDARY_COLOR, width=t)
    buf = BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf

# страница A4, поля как в шаблоне (3 / 1.5 / 2 / 2 см)
PAGE_W, PAGE_H = Cm(21.0), Cm(29.7)
M_LEFT, M_RIGHT, M_TOP, M_BOTTOM = Cm(3.0), Cm(1.5), Cm(2.0), Cm(2.0)
USABLE_W = Cm(21.0 - 3.0 - 1.5)          # 16.5 см
MAX_IMG_H = Cm(29.7 - 2.0 - 2.0 - 5.0)   # запас под подписи


def _run(par, text, size=12, bold=False):
    r = par.add_run(text)
    r.font.name = FONT
    r.font.size = Pt(size)
    r.bold = bold
    return r


def build_docx(map_image: BytesIO, territory: str, annex_no: str,
               out_path: pathlib.Path, line_px: int = 0,
               metric_text: str = ""):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = PAGE_W, PAGE_H
    sec.left_margin, sec.right_margin = M_LEFT, M_RIGHT
    sec.top_margin, sec.bottom_margin = M_TOP, M_BOTTOM

    # «Приложение __» справа
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(p, f"Приложение {annex_no or '__'}")

    # «Территория: …»
    p = doc.add_paragraph()
    _run(p, "Территория: ", bold=True)
    _run(p, territory)

    # «Ориентировочная площадь/протяжённость — …»
    if metric_text:
        p = doc.add_paragraph()
        _run(p, metric_text)

    # карта, вписанная в доступную область
    from PIL import Image
    map_image.seek(0)
    with Image.open(map_image) as im:
        aspect = im.height / im.width
        img_px_w = im.width
    from docx.shared import Emu
    width = USABLE_W
    if width * aspect > MAX_IMG_H:
        width = Emu(int(MAX_IMG_H / aspect))
    # толщина линии границы на листе, мм (для условного знака)
    line_mm = (line_px * (width.mm / img_px_w)) if line_px else 1.2
    map_image.seek(0)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(map_image, width=width)

    # условные обозначения — таблица, чтобы знак и текст были на одной линии
    from docx.enum.table import WD_ALIGN_VERTICAL

    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    c_sign, c_text = table.rows[0].cells
    c_sign.width = Cm(4.0)
    c_text.width = USABLE_W - Cm(4.0)
    for c in (c_sign, c_text):
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = c_sign.paragraphs[0]
    p.paragraph_format.space_before = Pt(6)
    p.add_run().add_picture(_make_swatch(line_mm), width=Cm(SWATCH_W_MM / 10))
    p = c_text.paragraphs[0]
    _run(p, "- ориентировочная граница разработки документации")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
