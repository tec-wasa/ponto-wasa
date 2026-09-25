"""Crachás impressos da Central do Ponto: um cartão por pessoa, com nome, código interno e o QR assinado."""
import io

import segno
from fpdf import FPDF

from .layout import latin1_safe

CARD_W, CARD_H, MARGIN_X, MARGIN_Y, GAP = 90, 60, 10, 12, 4  # mm: 2 colunas x 4 linhas por A4


def _qr_png(payload: str) -> io.BytesIO:
    buf = io.BytesIO()
    segno.make(payload, error="m", micro=False).save(buf, kind="png", scale=8, border=2)
    buf.seek(0)
    return buf


def badges_pdf(company: str, people: list[dict]) -> bytes:
    """`people`: dicts com name, job_title, code e qr. Recortar pelas bordas dos cartões."""
    pdf = FPDF(orientation="P", format="A4")
    pdf.set_title("Crachas do Ponto")
    pdf.set_author("Ponto")
    pdf.set_auto_page_break(False)
    for i, p in enumerate(people):
        slot = i % 8
        if slot == 0:
            pdf.add_page()
        x = MARGIN_X + (slot % 2) * (CARD_W + GAP)
        y = MARGIN_Y + (slot // 2) * (CARD_H + GAP)
        pdf.set_draw_color(150, 150, 150)
        pdf.rect(x, y, CARD_W, CARD_H)
        pdf.set_xy(x + 4, y + 4)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(47, 107, 91)
        pdf.cell(CARD_W - 8, 4, latin1_safe(company)[:44])
        pdf.set_text_color(30, 35, 32)
        pdf.set_xy(x + 4, y + 14)
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(50, 5.5, latin1_safe(p["name"])[:60])
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(x + 4, pdf.get_y() + 0.5)
        pdf.multi_cell(50, 4, latin1_safe(p.get("job_title") or ""))
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(91, 102, 96)
        pdf.set_xy(x + 4, y + CARD_H - 21)
        pdf.cell(50, 3.5, "Código interno")
        pdf.set_font("Courier", "B", 16)
        pdf.set_text_color(30, 35, 32)
        pdf.set_xy(x + 4, y + CARD_H - 17)
        pdf.cell(50, 7, p["code"])
        pdf.image(_qr_png(p["qr"]), x=x + CARD_W - 36, y=y + 12, w=32, h=32)
        pdf.set_font("Helvetica", "", 6)
        pdf.set_text_color(91, 102, 96)
        pdf.set_xy(x + 4, y + CARD_H - 7)
        pdf.cell(CARD_W - 8, 3, "Pessoal e intransferível. Aproxime o QR Code da Central do Ponto.")
    if not people:
        pdf.add_page()
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, "Nenhuma pessoa selecionada.")
    return bytes(pdf.output())
