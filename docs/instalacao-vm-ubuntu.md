# Instalação em VM Ubuntu Server (imagem construída na própria VM)

Cenário: Ubuntu Server 24.04 LTS em Hyper-V (Windows Server 2026), sem registro de imagens: o código vem do GitHub e a imagem é construída na VM.

## 1. Preparar a VM
```bash
sudo apt update && sudo apt -y upgrade
sudo timedatectl set-timezone America/Sao_Paulo
sudo apt -y install chrony git curl ca-certificates ufw
chronyc tracking            # "System time" deve ficar abaixo de 1 s; o app recusa batida com desvio > 30 s da Hora Legal
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```
Docker Engine + Compose v2 (repositório oficial):
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # sair e entrar de novo
docker run --rm hello-world
```
Hyper-V: rede em **switch externo** (a VM recebe IP da rede, acessível por tablet e celulares) e IP fixo (reserva no DHCP). Desative o "Time synchronization" do Hyper-V só se o `chrony` e o host divergirem.

## 2. Baixar o código e construir a imagem
```bash
git clone https://github.com/tec-wasa/ponto-wasa.git && cd ponto-wasa
git checkout main && git log --oneline | head -1
docker build -t ponto:local .        # ~3 a 5 min
```
(Repositório privado: use um token de leitura ou *deploy key*.)

## 3. Configurar
```bash
cd deploy && cp .env.example .env && chmod 600 .env && mkdir -p secrets
openssl rand -hex 24      # OWNER_DB_PASSWORD e APP_DB_PASSWORD (valores diferentes)
openssl rand -base64 36   # SECRET_KEY e TOTP_KEY (valores diferentes; guarde a TOTP_KEY junto do backup)
```
No `.env`: `PONTO_IMAGE=ponto:local`, `DOMAIN=<nome ou IP>`, senhas e chaves acima, `REQUIRE_2FA_ROLES=hr,admin` (opcional).

**HTTPS** (câmera e GPS do navegador exigem): 
- domínio público com 80/443 acessíveis da internet: o Caddy obtém o Let's Encrypt sozinho;
- só rede interna: use `tls internal` no Caddyfile (CA própria do Caddy). Cada tablet/celular precisa **instalar e confiar** o certificado raiz (`docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .`).

## 4. Subir e criar a empresa
```bash
docker compose up -d
docker compose logs migrate | tail -3        # "papel ponto_app configurado"
docker compose exec app python -m app.seed --name "Empresa" --cnpj 00.000.000/0001-00 \
  --email admin@empresa.com --password '<senha forte>' --cpf 000.000.000-00
curl -k https://localhost/api/ready          # {"status":"ready"}
```
Para dados de demonstração (só teste): `docker compose exec -e PONTO_ALLOW_MISSING_INPI=true app python -m app.seed_demo`.

## 5. Conferências antes dos testes
- `docker compose ps` (db e app *healthy*, backup rodando; `docker compose exec backup ls /backups`).
- `docker compose exec app python -m app.photos_check`.
- Gestão > Fiscalização: o que falta (INPI, certificado) aparece como pendência; no ensaio, tudo sai marcado TESTE.
- Restauração de teste: `docker compose exec backup bash /scripts/restore.sh /backups/<dump> ponto_restaurado`, depois `dbinit` e `app.integrity`.

## 6. Atualizar a VM
```bash
cd ~/ponto-wasa && git pull && docker build -t ponto:local . && cd deploy && docker compose up -d && docker compose exec app python -m app.integrity
```
