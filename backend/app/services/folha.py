"""Folha de Ponto mensal para assinatura: uma página A4 em retrato, no modelo usado pela empresa.

Cabeçalho (empregador e colaborador), quadro de horários da jornada, uma linha por dia (pontos em pares, trabalhadas,
abono, previstas, saldo), totais, resumo (horas extras, faltas, noturnas, banco de horas), ciência e assinaturas.
As marcações tratadas continuam identificáveis: incluídas levam "*" e todas as tratadas (incluídas e desconsideradas) vão em
"Observações", com o motivo. O detalhamento por NSR fica no espelho detalhado (services/espelho.py).
"""
import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, Company, Schedule, User, utcnow
from . import hourbank
from .layout import latin1_safe
from .mirror import justifications, month_days, schedule_rule, user_marks
from .punching import KIND_LABEL

WEEKDAY = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sabado", "domingo"]
WEEKDAY_CAP = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]


def hm(minutes: int | None, blank_zero: bool = False) -> str:
    if minutes is None or (blank_zero and minutes == 0):
        return ""
    sign = "-" if minutes < 0 else ""
    m = abs(int(minutes))
    return f"{sign}{m // 60:02d}:{m % 60:02d}"


def _add(hhmm: str, minutes: int) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    t = (h * 60 + m + minutes) % (24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


def schedule_periods(s: Schedule | None) -> list[str]:
    """Períodos da jornada ("08:00 às 12:00", "13:00 às 17:00") a partir de início, intervalo e carga diária."""
    if not s or not s.daily_minutes:
        return []
    start = s.start_time or "08:00"
    if s.break_minutes and s.break_start:
        first = (int(s.break_start[:2]) * 60 + int(s.break_start[3:])) - (int(start[:2]) * 60 + int(start[3:]))
        if s.crosses_midnight and first < 0:
            first += 24 * 60
        if 0 < first < s.daily_minutes:
            back = _add(s.break_start, s.break_minutes)
            return [f"{start} às {s.break_start}", f"{back} às {_add(back, s.daily_minutes - first)}"]
    return [f"{start} às {_add(start, s.daily_minutes)}"]


def build_folha(db: Session, company: Company, user: User, year: int, month: int, now: datetime | None = None) -> dict:
    zone = ZoneInfo(company.timezone)
    now = now or utcnow()
    days = month_days(db, user, company, year, month)
    sched = db.get(Schedule, user.schedule_id) if user.schedule_id else None
    rule = schedule_rule(sched)
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    just = justifications(db, user, first, last)

    def local(dt: datetime) -> datetime:
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)

    lo = datetime(year, month, 1) - timedelta(days=1)
    hi = datetime(year + (month == 12), month % 12 + 1, 1) + timedelta(days=1)
    punches, inclusions, voided = user_marks(db, user, lo, hi)
    included = {(local(a.requested_at).date(), f"{local(a.requested_at):%H:%M}") for a in inclusions}
    reasons = {a.target_punch_id: a.reason for a in db.execute(select(Adjustment).where(
        Adjustment.user_id == user.id, Adjustment.status == "approved", Adjustment.kind == "desconsiderar")).scalars()}
    notes = []
    for a in sorted(inclusions, key=lambda x: x.requested_at):
        w = local(a.requested_at)
        if first <= w.date() <= last:
            notes.append(f"{w:%d/%m %H:%M} {KIND_LABEL.get(a.punch_kind, '').lower()} incluída: {a.reason}")
    for p in sorted((p for p in punches if p.id in voided), key=lambda x: x.occurred_at):
        w = local(p.occurred_at)
        if first <= w.date() <= last:
            notes.append(f"{w:%d/%m %H:%M} {KIND_LABEL.get(p.kind, '').lower()} desconsiderada: {reasons.get(p.id, '')}")

    rows, totals = [], {"worked": 0, "abono": 0, "expected": 0, "balance": 0}
    extra50 = extra100 = late = faltas_min = night = ficta = 0
    faltas = 0
    for d in days:
        j = just.get(d.date)
        contract = rule.daily_minutes if d.date.weekday() in rule.weekdays else 0
        abono = 0
        if j and d.status not in ("anterior", "futuro"):
            abono = contract if j.minutes is None else min(j.minutes, contract)
        expected = d.expected + abono if d.status not in ("anterior", "futuro", "folga") else (d.expected if d.status == "folga" else 0)
        times = []
        for p in d.punches:
            hhmm = p[:5]
            times.append(hhmm + ("*" if (d.date, hhmm) in included else ""))
        if times:
            pairs = [" ".join(times[i:i + 2]) for i in range(0, len(times), 2)]
            pontos = " | ".join(pairs) + " |"
        elif d.status == "justificada":
            pontos = d.justification or "Ausência justificada"
        elif d.status == "falta":
            pontos = "Falta"
        elif d.status in ("futuro", "anterior"):
            pontos = ""
        else:
            pontos = "-"
        if d.status in ("futuro", "anterior"):
            rows.append({"date": d.date, "pontos": pontos, "worked": None, "abono": None, "expected": None, "balance": None})
            continue
        rows.append({"date": d.date, "pontos": pontos, "worked": d.worked, "abono": abono, "expected": expected,
                     "balance": d.balance})
        totals["worked"] += d.worked
        totals["abono"] += abono
        totals["expected"] += expected
        totals["balance"] += d.balance
        night += d.night_minutes
        ficta += max(0, d.reduced_minutes - d.worked)
        if d.status == "falta":
            faltas += 1
            faltas_min += -d.balance if d.balance < 0 else expected
        elif d.balance > 0:
            if contract:
                extra50 += d.balance
            else:
                extra100 += d.balance
        elif d.balance < 0 and d.punches:
            late += -d.balance

    bank = None
    if user.hour_bank_enabled:
        st = hourbank.statement(db, company, user, first, min(last, local(now).date()))
        bank = {"opening": st["opening"], "closing": st["closing"]}

    return {
        "period": (first, last),
        "employer": {"name": company.name, "cnpj": company.cnpj, "address": company.workplace or "", "local": "Local Padrão"},
        "worker": {"name": user.name, "cpf": "".join(c for c in user.cpf if c.isdigit()), "code": user.employee_code or "",
                   "admitted_at": user.admitted_at, "job_title": user.job_title or ""},
        "schedule": [(WEEKDAY_CAP[wd], schedule_periods(sched), hm(rule.daily_minutes)) for wd in sorted(rule.weekdays)] if sched else [],
        "rows": rows, "totals": totals, "notes": notes, "bank": bank,
        "summary": {"extra50": extra50, "extra100": extra100, "extras": extra50 + extra100, "late": late,
                    "faltas": faltas, "faltas_min": faltas_min, "night": night, "ficta": ficta},
        "issued_at": local(now),
    }


# ----------------------------------------------------------------------------------------------------------------------
GRAY = (200, 200, 200)
DARK = (60, 60, 60)


def _band(pdf: FPDF, text: str, x: float, w: float, h: float = 6) -> None:
    pdf.set_fill_color(*GRAY)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(x)
    pdf.cell(w, h, latin1_safe(text), fill=True, new_x="LMARGIN", new_y="NEXT")


def _fit(pdf: FPDF, text: str, width: float, size: float) -> None:
    """Diminui a fonte (até 5,5 pt) e, se ainda não couber, corta com reticências: nada invade o campo vizinho."""
    text = latin1_safe(text)
    while size > 5.5 and pdf.get_string_width(text) > width - 1:
        size -= 0.25
        pdf.set_font_size(size)
    while text and pdf.get_string_width(text + "...") > width - 1 and pdf.get_string_width(text) > width - 1:
        text = text[:-1]
    return text if pdf.get_string_width(text) <= width - 1 else text + "..."


def _pair(pdf: FPDF, label: str, value: str, x: float, y: float, lw: float, vw: float, size: float = 8.5) -> None:
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "", size)
    pdf.cell(lw, 5, latin1_safe(label))
    pdf.set_font("Helvetica", "", size - 1)
    pdf.cell(vw, 5, _fit(pdf, value, vw, size - 1) if vw else latin1_safe(value))


def folha_pdf(f: dict) -> bytes:
    pdf = FPDF(orientation="P", format="A4")
    pdf.set_title(latin1_safe("Folha de Ponto"))
    pdf.set_author("Ponto")
    pdf.set_auto_page_break(False)
    L, R, T = 10, 10, 10
    pdf.set_margins(L, T, R)
    pdf.add_page()
    W = pdf.w - L - R
    first, last = f["period"]
    emp, wk = f["employer"], f["worker"]

    # Título, período e marca
    pdf.set_xy(L, T + 2)
    pdf.set_font("Helvetica", "", 20)
    pdf.cell(0, 9, "Folha de Ponto", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"{first:%d/%m/%Y}   a   {last:%d/%m/%Y}", new_x="LMARGIN", new_y="NEXT")
    mark = (emp["name"].split() or ["EMPRESA"])[0][:8]
    pdf.set_fill_color(*DARK)
    pdf.rect(L + W - 14, T + 1, 14, 14, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_xy(L + W - 14, T + 5.5)
    pdf.cell(14, 5, latin1_safe(mark), align="C")
    pdf.set_text_color(0, 0, 0)

    # Dados do empregador
    pdf.set_y(T + 17)
    _band(pdf, "DADOS DO EMPREGADOR", L, W)
    y = pdf.get_y() + 1
    _pair(pdf, "Nome:", emp["name"], L + 2, y, 30, 120)
    _pair(pdf, "CNPJ:", emp["cnpj"], L + 136, y, 12, 40)
    _pair(pdf, "Endereço:", emp["address"], L + 2, y + 5.5, 30, 103)
    _pair(pdf, "Local:", emp["local"], L + 136, y + 5.5, 12, 40)

    # Dados do colaborador
    pdf.set_y(y + 12)
    _band(pdf, "DADOS DO COLABORADOR", L, W)
    y = pdf.get_y() + 1
    _pair(pdf, "Nome:", wk["name"].upper(), L + 2, y, 22, 92)
    _pair(pdf, "CPF:", wk["cpf"], L + 116, y, 9, 32)
    _pair(pdf, "Código:", wk["code"], L + 160, y, 14, 20)
    adm = wk["admitted_at"].strftime("%d/%m/%Y") if wk["admitted_at"] else ""
    _pair(pdf, "Admissão:", adm, L + 2, y + 5.5, 18, 20)
    _pair(pdf, "CTPS:", "", L + 40, y + 5.5, 10, 25)
    _pair(pdf, "Série:", "", L + 78, y + 5.5, 10, 25)
    _pair(pdf, "Cargo:", wk["job_title"].upper(), L + 116, y + 5.5, 12, 31)
    _pair(pdf, "Centro de Custo:", "", L + 160, y + 5.5, 28, 0, size=8)
    pdf.set_draw_color(0, 0, 0)
    pdf.line(L, y + 11.5, L + W, y + 11.5)

    # Quadro de horários
    y += 14
    cols = [("Dia", 30), ("PERÍODO 1", 22), ("PERÍODO 2", 22), ("PERÍODO 3", 20), ("PERÍODO 4", 20), ("PERÍODO 5", 20),
            ("PERÍODO 6", 20), ("Total", 16)]
    cols.append(("Local de Trabalho", W - sum(c[1] for c in cols)))
    pdf.set_fill_color(*GRAY)
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.cell(W, 5, "Quadro de Horários", border=1, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 7)
    for name, w in cols:
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(w, 5, _fit(pdf, name, w, 7), border=1, align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 7)
    sched_rows = f["schedule"] or [("Sem jornada definida", [], "")]
    for day, periods, total in sched_rows:
        values = [day] + [periods[i] if i < len(periods) else "" for i in range(6)] + [total, ""]
        for (_, w), v in zip(cols, values, strict=True):
            pdf.cell(w, 4.2, latin1_safe(v), border="LR", align="C")
        pdf.ln(4.2)
    pdf.line(L, pdf.get_y(), L + W, pdf.get_y())

    # Linhas do mês: altura calculada para tudo caber numa página
    y = pdf.get_y() + 3
    reserved = 76 + (4 if f["notes"] else 0) + 3.4 * min(len(f["notes"]), 4)
    rows = f["rows"]
    rh = max(3.2, min(4.6, (pdf.h - 8 - reserved - y - 5) / max(len(rows), 1)))
    widths = [16, 26, 64, 24, 14, 22, 24]
    heads = [("DIA / MÊS", "L"), ("", "L"), ("PONTOS", "L"), ("TRABALHADAS", "C"), ("ABONO", "R"), ("PREVISTAS", "C"), ("SALDO", "R")]
    pdf.set_fill_color(225, 225, 225)
    pdf.set_xy(L, y)
    pdf.set_font("Helvetica", "", 7.5)
    for (h, align), w in zip(heads, widths, strict=True):
        pdf.cell(w, 4.6, latin1_safe(h), align=align, fill=True)
    pdf.ln(4.6)
    pdf.set_font("Helvetica", "", 7.2)
    pdf.set_draw_color(150, 150, 150)
    for r in rows:
        d = r["date"]
        vals = [f"{d:%d/%m}", WEEKDAY[d.weekday()], r["pontos"], hm(r["worked"], True), hm(r["abono"], True),
                hm(r["expected"], True), hm(r["balance"], True)]
        aligns = ["C", "L", "L", "C", "R", "C", "R"]
        for v, w, a in zip(vals, widths, aligns, strict=True):
            pdf.cell(w, rh, latin1_safe(v), align=a)
        pdf.ln(rh)
        with pdf.local_context():
            pdf.set_dash_pattern(dash=0.6, gap=0.6)
            pdf.line(L, pdf.get_y(), L + W, pdf.get_y())
    pdf.set_draw_color(0, 0, 0)

    # Totais
    t = f["totals"]
    pdf.ln(1.5)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(sum(widths[:3]) - 4, 5, "Total:", align="R")
    pdf.cell(4, 5, "")
    pdf.cell(widths[3], 5, hm(t["worked"]), align="C")
    pdf.cell(widths[4], 5, hm(t["abono"]), align="R")
    pdf.cell(widths[5], 5, hm(t["expected"]), align="C")
    pdf.cell(widths[6], 5, hm(t["balance"]), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.line(L, pdf.get_y(), L + W, pdf.get_y())
    pdf.ln(1)
    pdf.cell(sum(widths[:3]) - 4, 5, "Trabalhadas + Abono:", align="R")
    pdf.cell(4, 5, "")
    pdf.cell(widths[3], 5, hm(t["worked"] + t["abono"]), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.line(L, pdf.get_y(), L + W, pdf.get_y())

    # Resumo
    s = f["summary"]
    y = pdf.get_y() + 2
    left = [("Hora extra diurna", ""), ("Tipo Hora Extra 01:   50%", hm(s["extra50"], True)),
            ("Tipo Hora Extra 02: 100%", hm(s["extra100"], True)), ("Tipo Hora Extra 03:", ""), ("Tipo Hora Extra 04:", ""),
            ("Horas Extras Totais:", hm(s["extras"], True)), ("Atrasos:", hm(s["late"], True))]
    mid = [("Dias Faltosos:", str(s["faltas"])), ("Faltas em Horas:", hm(s["faltas_min"], True)), ("Horas Sobreaviso:", ""),
           ("Horas Trabalhadas no Sobreaviso:", ""), ("Horas Não-Trabalhadas no Sobreaviso:", ""),
           ("Horas Noturnas:", hm(s["night"], True)), ("Horas Ficta:", hm(s["ficta"], True))]
    pdf.set_font("Helvetica", "", 7.5)
    for i, (label, value) in enumerate(left):
        _pair(pdf, label, value, L + 2, y + i * 3.9, 38, 20, size=7.5)
    for i, (label, value) in enumerate(mid):
        _pair(pdf, label, value, L + 88, y + i * 3.9, 52, 15, size=7.5)
    if f["bank"]:
        _pair(pdf, "Saldo Anterior de Banco de Horas:", hm(f["bank"]["opening"]), L + 148, y, 40, 12, size=7)
        _pair(pdf, f"Saldo Acumulado até {last:%d/%m/%Y}:", hm(f["bank"]["closing"]), L + 148, y + 3.9, 40, 12, size=7)
    y += 7 * 3.9 + 2

    # Observações: marcações tratadas (incluídas com * e desconsideradas), com o motivo
    if f["notes"]:
        pdf.set_xy(L + 2, y)
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(0, 3.6, latin1_safe("Observações (marcações tratadas; * = incluída pela gestão):"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 6.8)
        shown = f["notes"][:4]
        extra = len(f["notes"]) - len(shown)
        for n in shown:
            pdf.set_x(L + 2)
            pdf.cell(0, 3.4, latin1_safe(n[:150]), new_x="LMARGIN", new_y="NEXT")
        if extra > 0:
            pdf.set_x(L + 2)
            pdf.cell(0, 3.4, latin1_safe(f"e mais {extra} tratamento(s): veja o espelho detalhado."), new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y() + 1

    # Ciência e assinaturas
    pdf.set_xy(L + 2, y + 2)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, latin1_safe("Reconheço a exatidão e confirmo a frequência constante deste cartão."), new_x="LMARGIN", new_y="NEXT")
    ys = pdf.get_y() + 13
    col = 84
    pdf.line(L + 2, ys, L + 2 + col, ys)
    pdf.line(L + W - col - 4, ys, L + W - 4, ys)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(L + 2, ys + 1)
    pdf.cell(col, 4, latin1_safe(wk["name"].upper()), align="C")
    pdf.set_xy(L + W - col - 4, ys + 1)
    pdf.cell(col, 4, latin1_safe(emp["name"].upper()), align="C")

    # Rodapé
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(L + 2, pdf.h - 10)
    pdf.cell(60, 4, f"{f['issued_at']:%d/%m/%Y %H:%M}")
    pdf.set_xy(L + W - 40, pdf.h - 10)
    pdf.cell(38, 4, latin1_safe("Página 1 de 1"), align="R")
    return bytes(pdf.output())
