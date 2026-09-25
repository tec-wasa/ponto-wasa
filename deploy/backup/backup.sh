#!/usr/bin/env bash
# Backup lógico do PostgreSQL (pg_dump formato custom), com verificação, checksum e retenção.
#
# Variáveis: PGHOST/PGUSER/PGPASSWORD/PGDATABASE (padrão libpq), BACKUP_DIR (/backups),
#            BACKUP_INTERVAL_HOURS (1), BACKUP_KEEP (336 arquivos mais recentes), BACKUP_ONCE=true (uma vez e sai).
#
# RPO = intervalo entre backups (1 h por padrão). Para RPO menor, ou recuperação a um instante exato,
# use PostgreSQL gerenciado com PITR ou arquive o WAL; este script não substitui isso.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP:-336}"
INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-1}"

log() { printf '{"ts":"%s","service":"backup","msg":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }

backup_once() {
  local ts tmp final
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$BACKUP_DIR/.ponto-$ts.dump.partial"
  final="$BACKUP_DIR/ponto-$ts.dump"

  # --no-owner: a restauração não depende do papel dono original.
  pg_dump --format=custom --no-owner "${PGDATABASE:-ponto}" > "$tmp"
  pg_restore --list "$tmp" > /dev/null          # arquivo legível e completo
  mv "$tmp" "$final"
  (cd "$BACKUP_DIR" && sha256sum "$(basename "$final")" > "$(basename "$final").sha256")
  date +%s > "$BACKUP_DIR/last_success"         # para monitorar: se este arquivo envelhecer, o backup parou

  # Retenção: mantém os KEEP dumps mais recentes (nomes ordenam por data)
  local extra
  extra="$(ls -1 "$BACKUP_DIR"/ponto-*.dump 2>/dev/null | sort | head -n -"$KEEP" || true)"
  if [ -n "$extra" ]; then
    while IFS= read -r old; do rm -f "$old" "$old.sha256"; done <<< "$extra"
  fi
  log "backup ok: $(basename "$final") ($(du -h "$final" | cut -f1))"
}

if [ "${BACKUP_ONCE:-false}" = "true" ]; then
  mkdir -p "$BACKUP_DIR"
  backup_once
  exit 0
fi

mkdir -p "$BACKUP_DIR"
while true; do
  backup_once || log "ERRO: backup falhou; nova tentativa no próximo intervalo"
  sleep "$(( INTERVAL_HOURS * 3600 ))"
done
