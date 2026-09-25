# Sobe o Ponto localmente para teste: SQLite, modo de teste (sem INPI/certificado), front já compilado.
# Uso:  powershell -ExecutionPolicy Bypass -File run-local.ps1 [-Port 8765] [-Reset] [-Demo] [-DbFile <caminho>]
#   -Reset  apaga o banco local (backend\local.db) antes de subir: empresa, pessoas e marcacoes voltam do zero.
#   -Demo   cria empresa demo com gestor, RH, colaboradores e ~3 semanas de marcacoes (banco vazio; combine com -Reset).
#   -DbFile outro arquivo SQLite (padrao backend\local.db). Use um arquivo separado para experimentos, para nao mexer nos seus dados.
#   Sem flags, o banco existente e PRESERVADO: nada e apagado nem recriado. So o -Reset apaga.
param([int]$Port = 8765, [switch]$Reset, [switch]$Demo, [string]$DbFile = "")

$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Crie o ambiente: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt" }
if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
  Push-Location (Join-Path $root "frontend"); npm install; npm run build; Pop-Location
}

$db = if ($DbFile) { [IO.Path]::GetFullPath($DbFile) } else { Join-Path $root "backend\local.db" }
$env:PONTO_DATABASE_URL = "sqlite:///" + $db.Replace("\", "/")
if ($Reset) {
  Remove-Item $db -ErrorAction SilentlyContinue   # so o SQLite de teste deste script: nunca toca em outro banco
  Write-Host "Banco de teste apagado."
}
$env:PONTO_ALLOW_MISSING_INPI = "true"   # arquivos e comprovantes saem marcados como TESTE
Set-Location (Join-Path $root "backend")

$seed = (& $py -c "from app.db import SessionLocal, init_schema; from app.models import Company; init_schema(); print(SessionLocal().query(Company).count())" | Select-Object -Last 1)
if ($seed -ne "0") { Write-Host "Banco existente preservado ($db). Use -Reset para apagar e recomecar." }
if ($seed -eq "0" -and $Demo) {
  & $py -m app.seed_demo
} elseif ($seed -eq "0") {
  & $py -m app.seed --name "Empresa Teste" --cnpj 12.345.678/0001-90 --email admin@teste.com --password "senha-forte-123" --cpf 529.982.247-25
  Write-Host "Empresa criada. Entre com admin@teste.com / senha-forte-123 e cadastre colaboradores em Gestao."
} elseif ($Demo) {
  Write-Host "O banco ja tem dados: o -Demo so funciona em banco vazio. Use -Reset -Demo."
}
Write-Host "Abrindo em http://localhost:$Port  (Ctrl+C para parar)"
& $py -m uvicorn app.main:app --port $Port
