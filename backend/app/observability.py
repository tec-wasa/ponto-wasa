"""Logs estruturados (JSON), identificador de requisição e cabeçalhos de segurança."""
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Request

from .config import settings

log = logging.getLogger("ponto.request")

# Páginas do Swagger carregam scripts de CDN e usam inline: ficam fora da CSP estrita (e são desligadas em produção).
_CSP_EXEMPT = ("/docs", "/redoc", "/openapi.json")
# "Entrar com Google" (Google Identity Services): script, estilo, iframe do botão e chamadas em accounts.google.com/gsi.
_GSI = "https://accounts.google.com/gsi/"
CSP = (
    f"default-src 'self'; script-src 'self' {_GSI}client; style-src 'self' 'unsafe-inline' {_GSI}style; img-src 'self' data: blob:; "
    f"connect-src 'self' {_GSI}; frame-src {_GSI}; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",  # a janela do "Entrar com Google" precisa falar com a página
    # geolocalização só para o próprio site (registro de ponto); câmera e microfone nunca
    "Permissions-Policy": "geolocation=(self), camera=(self), microphone=(), payment=()",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_ponto", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler._ponto = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter() if settings.log_json else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("erro não tratado", extra={"extra_fields": {"request_id": request_id, "path": request.url.path}})
            raise
        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if not request.url.path.startswith(_CSP_EXEMPT):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            log.info("request", extra={"extra_fields": {
                "request_id": request_id, "method": request.method, "path": request.url.path,
                "status": response.status_code, "ms": round((time.perf_counter() - started) * 1000, 1),
                "ip": request.client.host if request.client else None,
            }})
        return response
