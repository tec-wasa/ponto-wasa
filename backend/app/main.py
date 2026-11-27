import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import (
    models,  # noqa: F401  (registra as tabelas)
    observability,
)
from .config import settings
from .db import SessionLocal, get_db, init_schema
from .routers import absences, admin, auth, exports, holidays, imports, inconsistencies, kiosk, panel, photos, punches, reports, workflow
from .services import arp

API_PREFIX = "/api"
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _service_event(code: str) -> None:
    try:
        with SessionLocal() as db:
            arp.record_service_event_all(db, code)
    except Exception:  # esquema ainda não migrado etc.: não impede a aplicação de subir/parar
        logging.getLogger("ponto").warning("Não foi possível registrar o evento %s no ARP", code, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()  # só em SQLite/dev; com PostgreSQL rode `alembic upgrade head`
    _service_event(arp.EVENT_AVAILABLE)  # ARP tipo 6, evento 07: disponibilidade de serviço
    yield
    _service_event(arp.EVENT_UNAVAILABLE)  # evento 08 (melhor esforço: quedas abruptas não deixam registro)


observability.configure_logging()
app = FastAPI(
    title="Ponto — registro e gestão de ponto eletrônico", version="0.3.0", lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None, redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
observability.install(app)

for r in (auth.router, admin.router, punches.router, workflow.router, exports.router, panel.router, absences.router, reports.router, photos.router, kiosk.router, holidays.router, imports.router, inconsistencies.router):
    app.include_router(r, prefix=API_PREFIX)


@app.get(f"{API_PREFIX}/health", tags=["infra"])
def health():
    """Liveness: o processo está de pé (não consulta o banco)."""
    return {"status": "ok"}


@app.get(f"{API_PREFIX}/ready", tags=["infra"])
def ready(db: Session = Depends(get_db)):
    """Readiness: o banco responde. Usado pelo orquestrador antes de mandar tráfego."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger("ponto").exception("readiness falhou")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


# --- Front-end (build do Vite), quando existir -------------------------------
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404)
        candidate = (DIST / full_path).resolve()
        if full_path and candidate.is_file() and DIST.resolve() in candidate.parents:
            target = candidate
        else:
            target = DIST / "index.html"
        headers = {"Cache-Control": "no-cache"} if target.name in ("index.html", "sw.js") else {}
        return FileResponse(target, headers=headers)
