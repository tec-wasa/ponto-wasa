#!/usr/bin/env bash
# Restaura um dump gerado por backup.sh em um banco NOVO (nunca sobrescreve um existente).
#
# Uso:  restore.sh <arquivo.dump> <nome_do_banco_novo>
# Usa PGHOST/PGUSER/PGPASSWORD (libpq); o usuário precisa poder criar bancos.
#
# Depois de restaurar: (1) python -m app.dbinit para reaplicar o papel restrito e (2) python -m app.integrity
# para conferir NSR e cadeia de hashes. Só então aponte a aplicação para o banco restaurado.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "uso: $0 <arquivo.dump> <banco_novo>" >&2
  exit 2
fi
dump="$1"
target="$2"

[ -f "$dump" ] || { echo "arquivo não encontrado: $dump" >&2; exit 2; }

if [ -f "$dump.sha256" ]; then
  (cd "$(dirname "$dump")" && sha256sum --check --status "$(basename "$dump").sha256") \
    || { echo "ERRO: checksum do dump não confere; arquivo corrompido ou adulterado" >&2; exit 3; }
  echo "checksum ok"
else
  echo "AVISO: sem arquivo .sha256; a integridade do dump não foi conferida" >&2
fi

pg_restore --list "$dump" > /dev/null || { echo "ERRO: dump ilegível" >&2; exit 3; }

if psql -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$target'" | grep -q 1; then
  echo "ERRO: o banco '$target' já existe; escolha um nome novo" >&2
  exit 4
fi

createdb "$target"
if ! pg_restore --no-owner --no-privileges --exit-on-error --dbname "$target" "$dump"; then
  echo "ERRO: falha ao restaurar; removendo o banco parcial '$target'" >&2
  dropdb --if-exists "$target"
  exit 5
fi
echo "restaurado em '$target'. Próximos passos: python -m app.dbinit e python -m app.integrity"
