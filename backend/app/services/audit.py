import json

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def _jsonable(value: dict | None) -> dict | None:
    """Datas e outros tipos não-JSON viram texto, para nunca quebrar a trilha."""
    return None if value is None else json.loads(json.dumps(value, default=str))


def log(
    db: Session,
    actor: User | None,
    action: str,
    entity: str,
    entity_id=None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
    company_id: int | None = None,
) -> None:
    db.add(
        AuditLog(
            company_id=company_id if company_id is not None else (actor.company_id if actor else None),
            actor_id=actor.id if actor else None,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=_jsonable(before),
            after=_jsonable(after),
            ip=ip,
        )
    )
