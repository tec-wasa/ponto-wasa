"""Feriados da empresa: calendário do ano (nacionais calculados + opcionais + cadastrados) e cadastro dos estaduais/municipais."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_user, require
from ..models import Closing, Company, Holiday, User
from ..services import audit
from ..services import holidays as svc

router = APIRouter(tags=["feriados"])


class HolidayIn(BaseModel):
    date: date
    name: str = Field(min_length=2, max_length=100)
    recurring: bool = True  # repete todo ano no mesmo dia e mês


class HolidayOptions(BaseModel):
    carnaval: bool | None = None
    corpus_christi: bool | None = None


def _closed_months(db: Session, company_id: int) -> set[str]:
    return {c.month for c in db.execute(select(Closing).where(Closing.company_id == company_id, Closing.status == "closed")).scalars()}


def _guard(db: Session, company: Company, days: list[date]) -> None:
    """Feriado muda o cálculo do dia: não pode entrar nem sair de um mês já fechado."""
    closed = _closed_months(db, company.id)
    hit = sorted({f"{d:%Y-%m}" for d in days} & closed)
    if hit:
        raise HTTPException(409, f"O mês {hit[0]} está fechado: reabra-o em Empresa > Fechamento para mudar os feriados dele.")


def _occurrences(db: Session, company: Company, day: date, recurring: bool) -> list[date]:
    """Datas afetadas: a própria, ou a mesma data em cada ano que tem mês fechado (para feriado que repete)."""
    if not recurring:
        return [day]
    years = {int(m[:4]) for m in _closed_months(db, company.id)} | {day.year}
    out = []
    for y in years:
        try:
            out.append(date(y, day.month, day.day))
        except ValueError:
            pass
    return out


@router.get("/holidays")
def list_holidays(year: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not 2000 <= year <= 2100:
        raise HTTPException(422, "Ano inválido")
    company = db.get(Company, user.company_id)
    return {"year": year, "carnaval": company.holiday_carnaval, "corpus_christi": company.holiday_corpus_christi,
            "holidays": svc.year_list(db, company, year)}


@router.post("/holidays", status_code=201)
def add_holiday(body: HolidayIn, request: Request, actor: User = Depends(require("company.settings")), db: Session = Depends(get_db)):
    company = db.get(Company, actor.company_id)
    _guard(db, company, _occurrences(db, company, body.date, body.recurring))
    existing = svc.company_holidays(db, company, body.date, body.date)
    if body.date in existing:
        raise HTTPException(409, f"{body.date:%d/%m/%Y} já é feriado: {existing[body.date]}")
    h = Holiday(company_id=company.id, day=body.date, name=body.name.strip(), recurring=body.recurring)
    db.add(h)
    db.flush()
    audit.log(db, actor, "create", "holiday", h.id, after={"date": str(body.date), "name": h.name, "recurring": h.recurring},
              ip=client_ip(request))
    db.commit()
    return {"id": h.id, "date": h.day, "name": h.name, "recurring": h.recurring}


@router.delete("/holidays/{holiday_id}", status_code=204)
def delete_holiday(holiday_id: int, request: Request, actor: User = Depends(require("company.settings")), db: Session = Depends(get_db)):
    h = db.get(Holiday, holiday_id)
    if not h or h.company_id != actor.company_id:
        raise HTTPException(404, "Feriado não encontrado")
    company = db.get(Company, actor.company_id)
    _guard(db, company, _occurrences(db, company, h.day, h.recurring))
    audit.log(db, actor, "delete", "holiday", h.id, before={"date": str(h.day), "name": h.name, "recurring": h.recurring},
              ip=client_ip(request))
    db.delete(h)
    db.commit()
    return Response(status_code=204)


@router.patch("/holidays/options")
def holiday_options(body: HolidayOptions, request: Request, actor: User = Depends(require("company.settings")),
                    db: Session = Depends(get_db)):
    """Carnaval (segunda e terça) e Corpus Christi: pontos facultativos nacionais que a empresa decide folgar."""
    company = db.get(Company, actor.company_id)
    changes = {}
    if body.carnaval is not None and body.carnaval != company.holiday_carnaval:
        changes["holiday_carnaval"] = body.carnaval
    if body.corpus_christi is not None and body.corpus_christi != company.holiday_corpus_christi:
        changes["holiday_corpus_christi"] = body.corpus_christi
    if changes:
        years = {int(m[:4]) for m in _closed_months(db, company.id)}
        days = []
        for y in years:
            days += list(svc.optional(y, "holiday_carnaval" in changes, "holiday_corpus_christi" in changes))
        _guard(db, company, days)
        for k, v in changes.items():
            setattr(company, k, v)
        audit.log(db, actor, "update", "company", company.id, after=changes, ip=client_ip(request))
        db.commit()
    return {"carnaval": company.holiday_carnaval, "corpus_christi": company.holiday_corpus_christi}
