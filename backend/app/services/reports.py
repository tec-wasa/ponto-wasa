"""Relatórios gerenciais (RF-19): fechamento mensal, banco de horas e ausências, em CSV e PDF.

Os dados vêm dos mesmos serviços das telas (espelho, banco, ausências): o relatório nunca calcula por conta própria.
O escopo segue o painel do gestor: o gestor vê a equipe; RH, administrador e auditor veem a empresa.
"""
import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as perm
from ..models import Absence, AuditLog, Company, Kiosk, Punch, User, utcnow
from . import absences as absences_svc
from . import hourbank, mirror, panel
from .layout import latin1_safe
from .mirror import ABSENCE_LABEL
from .pdf import NEXT_LINE, _br_date, _fmt_cpf, _hm, _new_pdf
from .punching import KIND_LABEL

MAX_PEOPLE = 500  # cada pessoa custa um cálculo mensal completo; acima disso, filtre por gestor
STATUS_LABEL = {"pending": "Pendente", "approved": "Aprovada", "rejected": "Rejeitada", "cancelled": "Cancelada"}


class ReportError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message, self.status = message, status


def scope(db: Session, actor: User) -> list[User]:
    users = panel.scope_users(db, actor)
    if len(users) > MAX_PEOPLE:
        raise ReportError(f"Escopo grande demais ({len(users)} pessoas; máximo {MAX_PEOPLE})", 413)
    return users


# --- Montagem dos dados ---------------------------------------------------------
def monthly(db: Session, company: Company, actor: User, year: int, month: int) -> dict:
    zone = ZoneInfo(company.timezone)
    rows = []
    for u in scope(db, actor):
        days = mirror.month_days(db, u, company, year, month)
        bank = hourbank.summary(db, company, u) if u.hour_bank_enabled else None
        rows.append({
            "name": u.name, "cpf": u.cpf, "job_title": u.job_title or "",
            "worked": sum(d.worked for d in days), "reduced": sum(d.reduced_minutes for d in days),
            "night": sum(d.night_minutes for d in days), "balance": sum(d.balance for d in days),
            "absences": sum(1 for d in days if d.status == "falta"),
            "justified": sum(1 for d in days if d.status == "justificada"),
            "incomplete": sum(1 for d in days if d.status == "incompleto"),
            "bank_balance": bank["balance"] if bank else None,
        })
    return {
        "title": "Fechamento mensal", "month": f"{year:04d}-{month:02d}", "company": company.name, "cnpj": company.cnpj,
        "issued_at": utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).strftime("%d/%m/%Y %H:%M"),
        "rows": rows,
        "totals": {k: sum(r[k] for r in rows) for k in ("worked", "reduced", "night", "balance", "absences", "justified", "incomplete")},
    }


def bank_report(db: Session, company: Company, actor: User) -> dict:
    zone = ZoneInfo(company.timezone)
    rows = []
    for u in scope(db, actor):
        if not u.hour_bank_enabled:
            continue
        s = hourbank.summary(db, company, u)
        rows.append({"name": u.name, "cpf": u.cpf, "balance": s["balance"], "limit": s["limit_minutes"],
                     "at_risk": s["at_risk_minutes"], "alerts": [a["message"] for a in s["alerts"]]})
    return {
        "title": "Banco de horas", "company": company.name, "cnpj": company.cnpj,
        "issued_at": utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).strftime("%d/%m/%Y %H:%M"),
        "rows": rows, "totals": {"balance": sum(r["balance"] for r in rows), "at_risk": sum(r["at_risk"] for r in rows)},
    }


def absences_report(db: Session, company: Company, actor: User, start: date, end: date, status: str | None) -> dict:
    if end < start or (end - start).days > 400:
        raise ReportError("Período inválido (máximo de 400 dias)")
    if status and status not in STATUS_LABEL:
        raise ReportError("Situação inválida")
    zone = ZoneInfo(company.timezone)
    if not perm.can(actor, "team.view"):
        raise ReportError("Sem permissão", 403)
    q = (select(Absence, User).join(User, User.id == Absence.user_id)
         .where(perm.scope_condition(actor, include_self=False), Absence.start_date <= end, Absence.end_date >= start))
    if status:
        q = q.where(Absence.status == status)
    rows = []
    for a, owner in db.execute(q.order_by(User.name, Absence.start_date)).all():
        detail = absences_svc.can_view_detail(actor, a)  # dado de saúde: só o RH/admin (e o dono) veem o motivo
        rows.append({
            "name": owner.name, "cpf": owner.cpf, "kind": ABSENCE_LABEL[a.kind], "start": a.start_date.isoformat(),
            "end": a.end_date.isoformat(), "days": (a.end_date - a.start_date).days + 1, "minutes": a.minutes,
            "status": STATUS_LABEL[a.status], "reason": a.reason if detail else "(restrito)",
        })
    return {
        "title": "Ausências justificadas", "company": company.name, "cnpj": company.cnpj,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "issued_at": utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).strftime("%d/%m/%Y %H:%M"),
        "rows": rows,
    }


def _window(company: Company, start: date, end: date) -> tuple[datetime, datetime, ZoneInfo]:
    """[início, fim) em UTC sem fuso (como o banco guarda) para os dias locais de start a end, inclusive."""
    if end < start or (end - start).days > 92:
        raise ReportError("Período inválido (máximo de 93 dias)")
    zone = ZoneInfo(company.timezone)
    lo = datetime.combine(start, time.min, zone).astimezone(UTC).replace(tzinfo=None)
    hi = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(UTC).replace(tzinfo=None)
    return lo, hi, zone


def _header(company: Company, title: str, start: date, end: date, zone: ZoneInfo) -> dict:
    return {
        "title": title, "company": company.name, "cnpj": company.cnpj,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "issued_at": utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).strftime("%d/%m/%Y %H:%M"),
    }


def punches_report(db: Session, company: Company, actor: User, start: date, end: date, origin: str) -> dict:
    """Batidas do período com a origem (Aplicativo ou Central) e a distância ao posto quando veio de uma Central."""
    if origin not in ("all", "app", "central"):
        raise ReportError("Origem deve ser all, app ou central")
    lo, hi, zone = _window(company, start, end)
    people = {u.id: u for u in scope(db, actor)}
    kiosks = {k.id: k for k in db.execute(select(Kiosk).where(Kiosk.company_id == actor.company_id)).scalars()}
    q = select(Punch).where(Punch.user_id.in_(people), Punch.occurred_at >= lo, Punch.occurred_at < hi)
    if origin == "app":
        q = q.where(Punch.kiosk_id.is_(None))
    elif origin == "central":
        q = q.where(Punch.kiosk_id.is_not(None))
    rows = []
    for p in db.execute(q.order_by(Punch.occurred_at, Punch.nsr)).scalars():
        owner, k = people[p.user_id], kiosks.get(p.kiosk_id)
        local = p.occurred_at.replace(tzinfo=UTC).astimezone(zone)
        rows.append({
            "at": local.strftime("%Y-%m-%d %H:%M:%S"), "name": owner.name, "cpf": owner.cpf, "nsr": p.nsr,
            "kind": KIND_LABEL.get(p.kind, p.kind), "origin": f"Central {k.name if k else p.kiosk_id}" if p.kiosk_id else "Aplicativo",
            "offline": p.offline, "distance_m": p.distance_m,
        })
    return {**_header(company, "Batidas por origem", start, end, zone), "rows": rows,
            "origin": {"all": "todas", "app": "aplicativo", "central": "Central"}[origin]}


def kiosk_divergences(db: Session, company: Company, actor: User, start: date, end: date) -> dict:
    """Central: batidas fora do raio ou sem localização, falhas de identificação e aparelhos sem sinal."""
    if not perm.can(actor, "reports.company"):
        raise ReportError("Sem permissão", 403)
    lo, hi, zone = _window(company, start, end)
    kiosks = {k.id: k for k in db.execute(select(Kiosk).where(Kiosk.company_id == actor.company_id)).scalars()}
    people = {u.id: u for u in db.execute(select(User).where(User.company_id == actor.company_id)).scalars()}
    rows = []

    def local(dt: datetime) -> str:
        return dt.replace(tzinfo=UTC).astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")

    q = select(Punch).where(Punch.kiosk_id.is_not(None), Punch.user_id.in_(people), Punch.occurred_at >= lo, Punch.occurred_at < hi)
    for p in db.execute(q.order_by(Punch.occurred_at)).scalars():
        k = kiosks.get(p.kiosk_id)
        if not k:
            continue
        if p.distance_m is None and k.latitude is not None:
            kind, detail = "Sem localização", "O aparelho não informou a posição no momento da batida"
        elif p.distance_m is not None and p.distance_m > k.radius_m:
            kind, detail = "Fora do posto", f"{p.distance_m} m do posto (raio de {k.radius_m} m)"
        else:
            continue
        rows.append({"at": local(p.occurred_at), "kind": kind, "kiosk": k.name, "person": people[p.user_id].name, "detail": f"NSR {p.nsr}: {detail}"})

    fails: dict[tuple[int, str], int] = {}
    aq = select(AuditLog).where(AuditLog.company_id == actor.company_id, AuditLog.action == "kiosk_identify_failed",
                                AuditLog.at >= lo, AuditLog.at < hi)
    for a in db.execute(aq).scalars():
        key = (int(a.entity_id or 0), local(a.at)[:10])
        fails[key] = fails.get(key, 0) + 1
    for (kid, day), n in sorted(fails.items(), key=lambda kv: kv[0][1]):
        k = kiosks.get(kid)
        rows.append({"at": day, "kind": "Falhas de identificação", "kiosk": k.name if k else str(kid), "person": "",
                     "detail": f"{n} tentativa(s) sem sucesso (código, CPF, QR ou PIN)"})

    rq = select(AuditLog).where(AuditLog.company_id == actor.company_id, AuditLog.action == "kiosk_offline_rejected",
                                AuditLog.at >= lo, AuditLog.at < hi)
    for a in db.execute(rq).scalars():
        k = kiosks.get(int(a.entity_id or 0))
        who = people.get(a.actor_id) if a.actor_id else None
        rows.append({"at": local(a.at), "kind": "Batida sem internet recusada", "kiosk": k.name if k else str(a.entity_id),
                     "person": who.name if who else "", "detail": (a.after or {}).get("reason", "")})

    now = utcnow()
    for k in kiosks.values():
        if k.active and k.token_hash and (k.last_seen_at is None or now - k.last_seen_at > timedelta(hours=1)):
            seen = "nunca" if k.last_seen_at is None else f"desde {local(k.last_seen_at)}"
            rows.append({"at": local(now), "kind": "Aparelho sem sinal", "kiosk": k.name, "person": "", "detail": f"Sem contato {seen}"})
    rows.sort(key=lambda r: r["at"])
    return {**_header(company, "Divergências da Central", start, end, zone), "rows": rows}


# --- CSV ------------------------------------------------------------------------
def _cell(value) -> str:
    """Neutraliza injeção de fórmula: nomes e motivos vêm de usuários e o CSV será aberto no Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        int(text)
        return True
    except ValueError:
        return False


def to_csv(header: list[str], rows: list[list]) -> bytes:
    """Ponto e vírgula e BOM UTF-8: abre direto no Excel em português."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow([_cell(c) for c in r])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def monthly_csv(d: dict) -> bytes:
    head = ["Nome", "CPF", "Cargo", "Trabalhado (min)", "Trabalhado (h:mm)", "Duração c/ hora noturna reduzida (min)",
            "Minutos noturnos", "Saldo do mês (min)", "Faltas", "Dias justificados", "Dias incompletos", "Saldo do banco (min)"]
    rows = [[r["name"], _fmt_cpf(r["cpf"]), r["job_title"], r["worked"], _hm(r["worked"]), r["reduced"], r["night"],
             r["balance"], r["absences"], r["justified"], r["incomplete"],
             "" if r["bank_balance"] is None else r["bank_balance"]] for r in d["rows"]]
    return to_csv(head, rows)


def bank_csv(d: dict) -> bytes:
    head = ["Nome", "CPF", "Saldo (min)", "Saldo (h:mm)", "Limite (min)", "Em risco de vencer (min)", "Alertas"]
    rows = [[r["name"], _fmt_cpf(r["cpf"]), r["balance"], _hm(r["balance"]), "" if r["limit"] is None else r["limit"], r["at_risk"], " | ".join(r["alerts"])]
            for r in d["rows"]]
    return to_csv(head, rows)


def absences_csv(d: dict) -> bytes:
    head = ["Nome", "CPF", "Tipo", "Início", "Fim", "Dias", "Minutos (parcial)", "Situação", "Motivo"]
    rows = [[r["name"], _fmt_cpf(r["cpf"]), r["kind"], _br_date(r["start"]), _br_date(r["end"]), r["days"],
             r["minutes"] or "", r["status"], r["reason"]] for r in d["rows"]]
    return to_csv(head, rows)


def punches_csv(d: dict) -> bytes:
    head = ["Data e hora", "Nome", "CPF", "NSR", "Batida", "Origem", "Sem internet", "Distância do posto (m)"]
    rows = [[r["at"], r["name"], _fmt_cpf(r["cpf"]), r["nsr"], r["kind"], r["origin"], "sim" if r["offline"] else "",
             r["distance_m"] if r["distance_m"] is not None else ""] for r in d["rows"]]
    return to_csv(head, rows)


def divergences_csv(d: dict) -> bytes:
    head = ["Data e hora", "Tipo", "Central", "Pessoa", "Detalhe"]
    return to_csv(head, [[r["at"], r["kind"], r["kiosk"], r["person"], r["detail"]] for r in d["rows"]])


# --- PDF ------------------------------------------------------------------------
def _table_pdf(d: dict, subtitle: str, heads: tuple, widths: tuple, rows: list[tuple], totals: tuple | None, note: str) -> bytes:
    pdf = _new_pdf(d["title"], format="A4", orientation="L")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 7, latin1_safe(d["title"]), **NEXT_LINE)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, latin1_safe(f"{d['company']} - CNPJ/CPF {d['cnpj']}"), **NEXT_LINE)
    pdf.multi_cell(0, 5, latin1_safe(f"{subtitle} - emitido em {d['issued_at']}"), **NEXT_LINE)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7.5)
    with pdf.table(col_widths=widths, line_height=4, first_row_as_headings=True, text_align="LEFT") as table:
        row = table.row()
        for h in heads:
            row.cell(latin1_safe(h))
        for r in rows:
            row = table.row()
            for text in r:
                row.cell(latin1_safe(str(text)))
        if totals:
            row = table.row()
            for text in totals:
                row.cell(latin1_safe(str(text)))
    if not rows:
        pdf.ln(2)
        pdf.cell(0, 5, "Nenhum registro no escopo e no período.", **NEXT_LINE)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7)
    pdf.multi_cell(0, 3.6, latin1_safe(note), **NEXT_LINE)
    return bytes(pdf.output())


def monthly_pdf(d: dict) -> bytes:
    y, m = d["month"].split("-")
    heads = ("Nome", "CPF", "Cargo", "Trabalhado", "Duração (hora noturna reduzida)", "Saldo do mês", "Faltas",
             "Justificados", "Incompletos", "Banco de horas")
    widths = (50, 26, 36, 22, 30, 22, 14, 20, 20, 25)
    rows = [(r["name"], _fmt_cpf(r["cpf"]), r["job_title"], _hm(r["worked"]), _hm(r["reduced"]), _hm(r["balance"]),
             r["absences"], r["justified"], r["incomplete"], "" if r["bank_balance"] is None else _hm(r["bank_balance"]))
            for r in d["rows"]]
    t = d["totals"]
    totals = ("Totais", "", "", _hm(t["worked"]), _hm(t["reduced"]), _hm(t["balance"]), t["absences"], t["justified"], t["incomplete"], "")
    note = ("Consolidado mensal do escopo do emitente, calculado como o Espelho de Ponto (jornada, tolerância legal, hora noturna "
            "reduzida e ausências justificadas). Não substitui o Espelho de Ponto individual (Art. 84), que é o documento oficial.")
    return _table_pdf(d, f"Competência {m}/{y}", heads, widths, rows, totals, note)


def bank_pdf(d: dict) -> bytes:
    heads = ("Nome", "CPF", "Saldo", "Limite", "Em risco de vencer", "Alertas")
    widths = (60, 30, 25, 25, 35, 100)
    rows = [(r["name"], _fmt_cpf(r["cpf"]), _hm(r["balance"]), "sem limite" if r["limit"] is None else _hm(r["limit"]), _hm(r["at_risk"]), "; ".join(r["alerts"]))
            for r in d["rows"]]
    t = d["totals"]
    return _table_pdf(d, "Posição atual", heads, widths, rows, ("Totais", "", _hm(t["balance"]), "", _hm(t["at_risk"]), ""),
                      "Só aparecem colaboradores que usam banco de horas. Saldo positivo = horas a compensar.")


def absences_pdf(d: dict) -> bytes:
    heads = ("Nome", "CPF", "Tipo", "Início", "Fim", "Dias", "Parcial", "Situação", "Motivo")
    widths = (45, 26, 32, 20, 20, 10, 16, 22, 86)
    rows = [(r["name"], _fmt_cpf(r["cpf"]), r["kind"], _br_date(r["start"]), _br_date(r["end"]), r["days"],
             _hm(r["minutes"]) if r["minutes"] else "", r["status"], r["reason"]) for r in d["rows"]]
    p = d["period"]
    return _table_pdf(d, f"Período {_br_date(p['start'])} a {_br_date(p['end'])}", heads, widths, rows, None,
                      "Motivos de atestado médico e afastamento (dado de saúde) só são exibidos ao RH e ao administrador.")


def punches_pdf(d: dict) -> bytes:
    heads = ("Data e hora", "Nome", "CPF", "NSR", "Batida", "Origem", "Sem internet", "Distância (m)")
    widths = (34, 60, 28, 16, 38, 50, 22, 24)
    rows = [(r["at"], r["name"], _fmt_cpf(r["cpf"]), r["nsr"], r["kind"], r["origin"], "sim" if r["offline"] else "",
             "" if r["distance_m"] is None else r["distance_m"]) for r in d["rows"]]
    p = d["period"]
    return _table_pdf(d, f"Período {_br_date(p['start'])} a {_br_date(p['end'])} - origem: {d['origin']}", heads, widths, rows, None,
                      "Lista das marcações (NSR) do escopo do emitente. A distância só existe nas batidas feitas em uma Central.")


def divergences_pdf(d: dict) -> bytes:
    heads = ("Data e hora", "Tipo", "Central", "Pessoa", "Detalhe")
    widths = (34, 42, 45, 55, 96)
    rows = [(r["at"], r["kind"], r["kiosk"], r["person"], r["detail"]) for r in d["rows"]]
    p = d["period"]
    return _table_pdf(d, f"Período {_br_date(p['start'])} a {_br_date(p['end'])}", heads, widths, rows, None,
                      "Divergências não bloqueiam a batida: servem para o RH conferir. Fora do posto = distância maior que o raio "
                      "cadastrado; sem localização = o aparelho não informou o GPS.")
