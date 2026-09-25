# Implantação e operação

Pilha em uma VM (qualquer nuvem ou servidor próprio) com Docker Compose: **PostgreSQL 18**, a aplicação
(API + PWA), **Caddy** (HTTPS automático) e um serviço de **backup**. Nada aqui depende de uma nuvem específica.

```
internet ──443──> caddy ──> app ──> db (PostgreSQL)        backup ──> volume de backups
                              └── (papel restrito ponto_app)
migrate (uma vez, como dono do banco): migra o esquema e cria/atualiza o papel restrito
```

## O que foi e o que não foi verificado

| Peça | Verificação feita |
| --- | --- |
| `dbinit`, papel restrito, migrações | Testes automatizados em PostgreSQL 18 e execução real do fluxo |
| Backup, retenção, restauração, checksum, integridade pós-restauração | Teste automatizado ponta a ponta em PostgreSQL 18 |
| Aplicação como na imagem (env do compose, papel restrito, logs JSON, docs desligadas, `X-Forwarded-For`) | Executada localmente contra PostgreSQL; CSP verificada no navegador |
| Workflows de CI/release | Validados com `actionlint`; **ainda não rodaram** (não há repositório remoto) |
| `Dockerfile` e `docker-compose.yml` | **Nunca construídos/executados**: não há Docker na máquina de desenvolvimento. O job `docker` da CI é o primeiro teste real; espere ajustes no primeiro push |
| Caddy/HTTPS | Não testado (depende de domínio e DNS reais) |

## Primeira instalação

Requisitos: VM Linux com Docker e Docker Compose v2, portas 80 e 443 abertas, e um domínio apontando para ela.

1. Publique a imagem: `git tag v0.3.0 && git push origin v0.3.0` (o `release.yml` roda toda a CI, varre a imagem e
   publica em `ghcr.io/<org>/<repo>:0.3.0`). Se o repositório for privado, faça `docker login ghcr.io` na VM.
2. Na VM, copie a pasta `deploy/` e crie o `.env`:
   ```bash
   cp .env.example .env && chmod 600 .env
   openssl rand -hex 24   # use para OWNER_DB_PASSWORD e APP_DB_PASSWORD (só letras e números: vão em URLs)
   openssl rand -base64 36  # SECRET_KEY
   ```
   Preencha `PONTO_IMAGE` (versão fixa, nunca `:latest`), `DOMAIN` e o restante.
3. `mkdir -p secrets` (o certificado ICP-Brasil, quando houver, vai aqui como `.p12`; aponte `SIGNING_P12_PATH`
   para `/run/secrets/ponto/<arquivo>.p12`).
4. `docker compose up -d`. Acompanhe: `docker compose logs -f migrate app`.
5. Primeira empresa e administrador:
   ```bash
   docker compose exec app python -m app.seed --name "Empresa" --cnpj 00.000.000/0001-00 \
     --email admin@empresa.com --password '<senha forte>' --cpf 000.000.000-00
   ```
6. Confira: `https://<domínio>/api/ready` responde `{"status":"ready"}` e a aba **Gestão → Fiscalização** mostra o que
   ainda falta (INPI, certificado, NTP).

## Atualizar e reverter

```bash
# atualizar: troque PONTO_IMAGE no .env para a nova versão
docker compose pull app migrate && docker compose up -d
docker compose exec app python -m app.integrity   # NSR e hashes íntegros (sai com código 1 se não)
```

A migração roda antes da aplicação (serviço `migrate`). **Reverter o código:** volte `PONTO_IMAGE` e `up -d`. Se a
versão nova trouxe migração de esquema, reverter também exige o `downgrade` correspondente; teste isso antes em
homologação e prefira migrações compatíveis com a versão anterior (adicionar colunas, nunca remover na mesma versão).

## Backups e restauração

- O serviço `backup` faz `pg_dump` a cada `BACKUP_INTERVAL_HOURS` (padrão 1 h), valida o arquivo, grava o checksum
  e mantém os `BACKUP_KEEP` mais recentes (padrão 336 = 14 dias de backups horários).
- **RPO = o intervalo (1 h por padrão). RTO = minutos** para bancos pequenos (tempo do `pg_restore`). Para RPO de
  segundos, ou voltar a um instante exato, use PostgreSQL gerenciado com PITR ou arquive o WAL; este backup lógico
  não substitui isso.
- **Cópia fora do servidor é obrigatória** (a VM e o volume de backup falham juntos). Envie `/backups` para um
  armazenamento externo (bucket com versionamento, ou outra máquina). Isso **não** está automatizado aqui.
- Monitore: o arquivo `last_success` (época Unix) em `/backups` deve envelhecer no máximo `BACKUP_INTERVAL_HOURS`.
  O `backup.sh` escreve `"ERRO: backup falhou"` em JSON nos logs quando falha.

Restaurar (num banco **novo**; o script se recusa a sobrescrever):

```bash
docker compose exec backup ls /backups                       # escolha um dump
docker compose exec backup bash /scripts/restore.sh /backups/ponto-AAAAMMDDTHHMMSSZ.dump ponto_restaurado
# reaplique o papel restrito e confira NSR e hashes no banco restaurado antes de usá-lo:
docker compose run --rm -e PONTO_OWNER_DATABASE_URL=postgresql+psycopg://ponto_owner:<senha>@db/ponto_restaurado \
  -e PONTO_APP_DB_PASSWORD=<senha da app> migrate
docker compose run --rm -e PONTO_DATABASE_URL=postgresql+psycopg://ponto_app:<senha>@db/ponto_restaurado app python -m app.integrity
```

Depois aponte a aplicação para o novo banco (ou renomeie os bancos). **Teste a restauração periodicamente**:
backup que nunca foi restaurado não é backup.

## Segurança operacional

- Só as portas 80/443 ficam abertas; o banco não publica porta.
- `.env` e `secrets/` nunca vão para o git (estão no `.gitignore`); permissão `600`.
- Trocar `SECRET_KEY` desconecta todos os usuários. Trocar `APP_DB_PASSWORD`: edite o `.env` e rode `docker compose up -d`
  (o `migrate` atualiza a senha do papel).
- **Contas:** usuários criados pelo RH (ou importados por CSV) nascem com senha temporária e são obrigados a trocá-la no
  primeiro acesso; trocar a senha, redefinir ou mudar o 2FA derruba as demais sessões. Defina `REQUIRE_2FA_ROLES=hr,admin`
  para exigir 2FA de quem tem acesso amplo aos dados. Perdeu o celular e os códigos de recuperação: o RH/administrador usa
  "Zerar 2FA" em Gestão → Colaboradores. Faça backup da `TOTP_KEY` junto com o do banco.
- A aplicação usa o papel `ponto_app` (sem UPDATE/DELETE/TRUNCATE em marcações e auditoria e sem ALTER TABLE).
  O dono (`ponto_owner`) só é usado pelo `migrate` e pelo `backup`.
- Logs em JSON (uma linha por evento, com `request_id`); nunca contêm senha nem e-mail. Login: 5 falhas por e-mail
  em 15 min bloqueiam o e-mail (HTTP 429); há também um teto por IP.
- Relógio: mantenha o NTP do servidor ativo (chrony/systemd-timesyncd). A aplicação recusa marcações se o relógio
  divergir mais de 30 s do NTP.br (`CLOCK_CHECK_ENABLED=true`).

## Limites conhecidos

- **Um único servidor**: não há alta disponibilidade (o Anexo IX do REP-P pede alta disponibilidade; PostgreSQL
  gerenciado com réplica e mais de uma instância da aplicação atrás de um balanceador resolvem isso, e exigem
  escolher a nuvem).
- **Escala**: a geração de NSR serializa as gravações por empresa (por desenho). `WEB_CONCURRENCY` > 1 aumenta o
  processamento de leitura, mas cada processo registra os eventos 07/08 do REP-P ao iniciar/parar.
- **Sem IaC de nuvem** (Terraform etc.): depende da escolha do provedor, ainda em aberto.
- **Métricas** (Prometheus/alertas): só há logs estruturados e as rotas `/api/health` e `/api/ready`.
