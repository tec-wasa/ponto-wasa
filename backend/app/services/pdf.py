"""Geração de PDFs: Comprovante de Registro de Ponto do Trabalhador (Art. 79) e Espelho de Ponto (Art. 84)."""
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from .layout import latin1_safe

NEXT_LINE = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}


def _fmt_cpf(cpf: str) -> str:
    d = "".join(c for c in cpf if c.isdigit())
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else cpf


def _new_pdf(title: str, format: str = "A5", orientation: str = "P") -> FPDF:
    pdf = FPDF(orientation=orientation, format=format)
    pdf.set_title(latin1_safe(title))
    pdf.set_author("Ponto")
    pdf.set_creator("Ponto - registro eletronico de ponto (REP-P)")
    compact = orientation == "L"  # espelho: tabela longa, margens menores para caber um mês numa página
    pdf.set_auto_page_break(True, margin=8 if compact else 12)
    pdf.set_margins(10 if compact else 12, 8 if compact else 12, 10 if compact else 12)
    pdf.add_page()
    return pdf


def receipt_pdf(r: dict, signed: bool = True) -> bytes:
    """`r`: campos do ReceiptOut. Contém tudo o que o Art. 79 exige, incluindo o hash SHA-256 (inciso VIII)."""
    pdf = _new_pdf(r["title"])
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 6, latin1_safe(r["title"]), align="C", **NEXT_LINE)
    pdf.ln(3)

    employer = f"{r['employer']} - CNPJ/CPF {r['cnpj']}" + (f" - CAEPF/CNO {r['caepf_cno']}" if r.get("caepf_cno") else "")
    rows = [
        ("NSR", str(r["nsr"])),
        ("Empregador", employer),
        ("Local da prestação", r.get("workplace") or "Não informado"),
        ("Trabalhador", f"{r['employee']} - CPF {_fmt_cpf(r['cpf'])}"),
        ("Data e hora", r["occurred_at_local"]),
        ("Registro no INPI", r.get("inpi") or "Não informado"),
    ]
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(38, 5.5, latin1_safe(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5.5, latin1_safe(value), **NEXT_LINE)
        pdf.ln(0.8)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5.5, "Código hash (SHA-256) da marcação", **NEXT_LINE)
    pdf.set_font("Courier", "", 8)
    pdf.multi_cell(0, 4.5, r["hash"], **NEXT_LINE)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B" if not signed else "", 8)
    note = ("Documento assinado eletronicamente com certificado digital ICP-Brasil (Portaria MTP 671/2021, art. 80). "
            "Verifique a assinatura no leitor de PDF." if signed else
            "DOCUMENTO DE TESTE: sem assinatura ICP-Brasil. Inválido como comprovante de registro de ponto.")
    pdf.multi_cell(0, 4, latin1_safe(note), **NEXT_LINE)
    return bytes(pdf.output())


def _hm(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    m = abs(minutes)
    return f"{sign}{m // 60}h{m % 60:02d}"


def _lines(items: list[str]) -> str:
    """Um item por linha. Cada item é sanitizado sozinho: quebras de linha só existem entre os itens."""
    return "\n".join(latin1_safe(i) for i in items)


def _br_date(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def espelho_pdf(e: dict) -> bytes:
    """Espelho de Ponto Eletrônico (Art. 84), A4 paisagem."""
    pdf = _new_pdf("Espelho de Ponto Eletrônico", format="A4", orientation="L")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 7, "Espelho de Ponto Eletrônico", **NEXT_LINE)

    emp, w, c = e["employer"], e["worker"], e["contract"]
    header = [
        ("Empregador", f"{emp['name']} - CNPJ/CPF {emp['id']}" + (f" - CAEPF/CNO {emp['caepf_cno']}" if emp.get("caepf_cno") else "")),
        ("Trabalhador", f"{w['name']} - CPF {_fmt_cpf(w['cpf'])} - Admissão {_br_date(w['admitted_at'])} - Cargo/função: {w['job_title']}"),
        ("Período", f"{_br_date(e['period']['start'])} a {_br_date(e['period']['end'])} - emitido em {e['issued_at']}"),
        ("Horário contratual", f"{c['name']}: {c['periods']} ({c['weekdays'] or 'sem dias definidos'}); jornada diária de {_hm(c['daily_minutes'])}"),
    ]
    for label, value in header:
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(36, 5, latin1_safe(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(0, 5, latin1_safe(value), **NEXT_LINE)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 7.5)
    widths = (20, 11, 40, 54, 60, 17, 24, 17, 30)
    heads = ("Data", "Dia", "Horário contratual", "Marcações no REP", "Marcações tratadas", "Trabalhado",
             "Duração (hora noturna reduzida)", "Saldo", "Situação")
    with pdf.table(col_widths=widths, line_height=3.8, first_row_as_headings=True, text_align="LEFT") as table:
        row = table.row()
        for h in heads:
            row.cell(h)
        for r in e["rows"]:
            row = table.row()
            for text in (
                _br_date(r["date"]), r["weekday"], r["contract"], _lines(r["rep"]), _lines(r["treated"]),
                _hm(r["worked"]) if r["worked"] else "", _hm(r["reduced"]) if r["reduced"] else "",
                _hm(r["balance"]) if r["balance"] else "", _lines([r["status"], *r["warnings"]]),
            ):
                row.cell(text)
        t = e["totals"]
        row = table.row()
        for text in ("Totais", "", "", "", "", _hm(t["worked"]), _hm(t["reduced"]), _hm(t["balance"]), f"Faltas: {t['absences']}"):
            row.cell(text)

    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7)
    pdf.multi_cell(0, 3.6, latin1_safe(
        "Marcações no REP: registradas no REP-P, com o NSR. Marcações tratadas: incluídas manualmente ou desconsideradas "
        "pelo programa de tratamento, com o motivo; o registro original no REP nunca é alterado. "
        "Saídas de turnos que atravessam a meia-noite aparecem no dia em que o turno começou, com a indicação (dia seguinte). "
        "Duração: tempo trabalhado considerando a hora noturna reduzida (22h às 5h; 52 min 30 s = 1 hora). "
        "Saldo: diferença para a jornada contratual, já aplicada a tolerância legal."), **NEXT_LINE)

    # Ciência do empregado e do empregador (assinatura no fim do mês). Fica inteira na mesma página.
    if pdf.get_y() > pdf.h - pdf.b_margin - 42:
        pdf.add_page()
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.multi_cell(0, 4.5, latin1_safe(
        f"Declaro que conferi as marcações e os totais deste espelho, referentes ao período de {_br_date(e['period']['start'])} a "
        f"{_br_date(e['period']['end'])}. Divergências devem ser comunicadas por escrito ao empregador."), **NEXT_LINE)
    pdf.ln(4)
    pdf.cell(0, 5, latin1_safe("Local e data: ______________________________, ____/____/________"), **NEXT_LINE)
    pdf.ln(12)
    col = (pdf.w - pdf.l_margin - pdf.r_margin - 20) / 2
    x0 = pdf.l_margin
    y = pdf.get_y()
    pdf.line(x0, y, x0 + col, y)
    pdf.line(x0 + col + 20, y, x0 + 2 * col + 20, y)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_xy(x0, y + 1)
    pdf.cell(col, 4.5, latin1_safe(w["name"]), align="C")
    pdf.set_xy(x0 + col + 20, y + 1)
    pdf.cell(col, 4.5, latin1_safe(emp["name"]), align="C", **NEXT_LINE)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_x(x0)
    pdf.cell(col, 4, latin1_safe(f"Empregado(a) - CPF {_fmt_cpf(w['cpf'])}"), align="C")
    pdf.set_xy(x0 + col + 20, pdf.get_y())
    pdf.cell(col, 4, latin1_safe(f"Empregador - CNPJ/CPF {emp['id']}"), align="C", **NEXT_LINE)
    return bytes(pdf.output())
