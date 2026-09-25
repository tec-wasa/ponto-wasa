# syntax=docker/dockerfile:1
# Imagem única: front-end compilado (Vite) + API (FastAPI). O FastAPI serve o front em produção.

# --- 1) Front-end ---------------------------------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2) Dependências Python (camada própria: só reconstrói se requirements.txt mudar) ---------------
FROM python:3.14-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY backend/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt

# --- 3) Imagem final ------------------------------------------------------------------------------
FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" \
    PONTO_LOG_JSON=true PONTO_DOCS_ENABLED=false WEB_CONCURRENCY=1
# /data/photos: o volume das fotos herda este dono
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin ponto \
    && mkdir -p /data/photos \
    && chown ponto:ponto /data/photos
COPY --from=deps /opt/venv /opt/venv
WORKDIR /srv/ponto
# O código espera esta estrutura: backend/app, frontend/dist (servido em /) e deploy/postgres-roles.sql (dbinit).
COPY backend/app backend/app
COPY backend/migrations backend/migrations
COPY backend/alembic.ini backend/alembic.ini
COPY deploy/postgres-roles.sql deploy/postgres-roles.sql
COPY --from=frontend /src/frontend/dist frontend/dist
USER ponto
WORKDIR /srv/ponto/backend
EXPOSE 8000

# Readiness: 200 só se o banco responde.
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=3).status == 200 else 1)"

# --proxy-headers: o IP real do cliente (auditoria e limite de login) vem do proxy; FORWARDED_ALLOW_IPS
# restringe de quem se aceita esse cabeçalho (defina na rede do proxy). Workers: WEB_CONCURRENCY.
# --no-access-log: a aplicação já registra cada requisição em JSON (com id de correlação); evita linhas duplicadas em texto.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
