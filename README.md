# Ponto — registro e gestão de ponto eletrônico (REP-P)

Back-end em Python (FastAPI + SQLAlchemy + Alembic) e front-end PWA em React + TypeScript (Vite).
O PRD e o backlog estão no doc "PRD — Aplicativo de Registro e Gestão de Ponto".

## Rodar em desenvolvimento (SQLite)

```bash
cd frontend && npm install && npm run build          # gera frontend/dist
cd ../backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
python -m app.seed --name "Minha Empresa" --cnpj 00.000.000/0001-00 --email admin@x.com --password 'senha-forte-123' --cpf 529.982.247-25
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Abra http://127.0.0.1:8000 (app) ou http://127.0.0.1:8000/docs (API). A API fica sob `/api`.
Front com recarga automática: `cd frontend && npm run dev` (proxy de `/api` para a porta 8000).

## Produção (PostgreSQL + Alembic)

Em PostgreSQL o esquema vem **somente** das migrações (a aplicação não cria tabelas sozinha).

```bash
export PONTO_DATABASE_URL=postgresql+psycopg://dono:senha@host/ponto     # dono do banco: só para migrar
alembic upgrade head                                                     # cria tabelas + gatilhos de imutabilidade
psql -f ../deploy/postgres-roles.sql ponto                               # cria o papel restrito ponto_app (troque CHANGE_ME)
export PONTO_DATABASE_URL=postgresql+psycopg://ponto_app:senha@host/ponto  # a aplicação usa o papel restrito
export PONTO_SECRET_KEY=<>=32 caracteres aleatórios>
python -m app.seed ... --cpf ...                                         # primeira empresa e administrador (CPF obrigatório)
uvicorn app.main:app
```

**Por que dois usuários no banco:** `punches` e `audit_log` são append-only por três camadas: guarda no ORM,
gatilhos no banco (UPDATE/DELETE/TRUNCATE) e o papel `ponto_app`, que não tem esses privilégios nem
`ALTER TABLE`, portanto não consegue desativar os gatilhos. Nunca rode a aplicação como dono das tabelas.

Novas alterações de modelo: `alembic revision --autogenerate -m "descrição"`, revisar o arquivo gerado e
`alembic upgrade head`. O teste `test_migrations` falha se o modelo divergir das migrações.

Variáveis (prefixo `PONTO_`): `DATABASE_URL`, `SECRET_KEY`, `AUTO_CREATE_TABLES` (padrão: só em SQLite).

## CI/CD e infraestrutura

- **CI** (`.github/workflows/ci.yml`, GitHub Actions): lint (ruff), testes do backend em SQLite **e** em PostgreSQL 18
  (concorrência do NSR, gatilhos, migrações, papel restrito, `dbinit`, backup/restauração), front-end (tipos, testes,
  build), construção da imagem com teste de fumaça e subida da pilha (`db -> migrate -> app`) com o papel restrito.
- **Release** (`release.yml`): a tag `v*` roda toda a CI, varre a imagem (Trivy) e publica no GHCR com SBOM e proveniência.
- **Dependabot** semanal para pip, npm, Docker e Actions. Auditoria de dependências (informativa) no job `security`.
- **Implantação**: `deploy/` (Compose com PostgreSQL, aplicação, Caddy com HTTPS e backups) e o roteiro completo em
  [`deploy/README.md`](deploy/README.md), incluindo o que **não** foi verificado (Docker e Caddy ainda não rodaram).
- **Operação**: `/api/health` (vivo) e `/api/ready` (banco responde), logs JSON com `request_id`, cabeçalhos de segurança
  (CSP estrita, `X-Frame-Options`, etc.), limite de tentativas de login, `python -m app.integrity` (confere NSR e hashes;
  sai com 1 se houver problema), `python -m app.dbinit` (migra e cria o papel restrito).
- Variáveis novas: `PONTO_LOG_JSON`, `PONTO_LOG_LEVEL`, `PONTO_DOCS_ENABLED` (desligar em produção),
  `PONTO_LOGIN_MAX_FAILURES`, `PONTO_LOGIN_WINDOW_MINUTES`, `PONTO_LOGIN_MAX_FAILURES_PER_IP`.

## Central do Ponto: servidor (fase 1)

Aparelho compartilhado (tablet) onde cada pessoa se identifica e registra o ponto **com foto obrigatória**. Plano completo em `docs/central-do-ponto.md`. Esta fase entrega só o servidor (API e testes); a tela `/central`, a aba de Gestão e o "Meu crachá" do aplicativo vêm nas próximas fases.

- **Aparelho:** o administrador cadastra a Central (`POST /kiosks`: nome, posto em latitude/longitude, raio, padrão 100 m) e recebe um **código de pareamento** de 8 caracteres (uso único, vale 15 min). O tablet troca o código por um token (`POST /kiosk/pair`); o servidor guarda só o hash. Revogar (`POST /kiosks/{id}/revoke`) ou refazer o pareamento (`.../pairing`) corta o acesso na hora. Limite de 5 centrais ativas por empresa.
- **Pessoa:** identifica-se por **código interno** (6 dígitos, gerado pelo sistema, sem relação com o CPF), **CPF**, **QR do crachá impresso** (assinado, com versão: regenerar invalida os impressos) ou **QR rotativo do aplicativo** (30 s, uso único por janela). O **PIN é configurável pelo administrador** (`PATCH /company {kiosk_pin_required}`, padrão desligado); o QR rotativo dispensa o PIN. PIN de 4 a 6 números, com hash argon2 e bloqueio de 5 min depois de 5 erros; PIN óbvio (1234, 0000, repetido) é recusado; definir o PIN pede a senha atual (`POST /auth/pin`).
- **Sem enumeração:** código inexistente, CPF inexistente, QR inválido, pessoa inativa, PIN errado e conta bloqueada respondem **a mesma mensagem** (401). Só o QR (que já é segredo) pode dizer "falta o PIN", sem revelar nome. Mais de 30 falhas em 5 min num aparelho respondem 429 para todos.
- **Batida:** `POST /kiosk/identify` devolve um **ticket de 60 s, uso único**, o primeiro nome e a próxima batida; `POST /kiosk/consent-photo` registra o consentimento LGPD na própria Central; `POST /kiosk/punch` grava a marcação (hora do servidor, ordem das batidas, jornada encerrada, coletor `04`, `device_id=kiosk:<id>`) e a **foto, obrigatória**, na mesma transação: se o armazenamento de fotos falhar, **nada é gravado** e o ticket continua valendo. Reenvio com o mesmo `client_key` não duplica.
- **Local:** a posição enviada é a do **aparelho**, guardada mesmo sem consentimento de GPS da pessoa; o servidor calcula a distância ao posto (`distance_m`) e marca `outside_radius`, sem nunca bloquear.
- **Pessoas (Gestão/API):** `GET /users/{id}/badge` (código e QR impresso), `POST /users/{id}/badge/regenerate`, `POST /users/{id}/pin-reset` (RH/admin; RH não mexe em contas de RH/admin). Colaborador: `GET /auth/badge` (código, tem PIN), `GET /auth/badge-qr` (QR rotativo), `POST /auth/pin`.
- **Dados:** migração `0008` (tabelas `kiosks` e `kiosk_tickets`; colunas de código/PIN/crachá em `users`, `kiosk_pin_required` em `companies`, `kiosk_id` e `distance_m` em `punches`); quem já existia recebe um código na migração. **Hash da marcação inalterado.** No PostgreSQL, `deploy/postgres-roles.sql` já inclui as tabelas novas.
- **Hipóteses:** **H8**: o coletor `04` do AFD para "central em tablet compartilhado" precisa ser confirmado na homologação.
- **Limites:** sem PIN exigido, código ou CPF sozinho identifica: trate o código como senha. A foto é indício, não prova de identidade.

## Central do Ponto: tela `/central` (fase 3)

Aplicativo à parte para o tablet compartilhado: abre em `https://<domínio>/central`, sem login de pessoa, com manifesto próprio (`central.webmanifest`, tela cheia, instalável como "Ponto Central"). Código em `frontend/src/central/`.

- **Pareamento:** na primeira abertura pede o código de pareamento gerado pelo administrador (hoje por `POST /kiosks`; a aba "Centrais" da Gestão é a fase 2). O token do aparelho fica no `localStorage`; se o servidor revogar, a tela volta sozinha ao pareamento com o aviso.
- **Fluxo:** Espera → Identificar (QR pela câmera, ou código interno/CPF no teclado) → PIN (só se o administrador exigir; **antes** de mostrar o nome) → consentimento da foto (primeira vez) → Confirmar (nome e próxima batida, ex.: "3ª · Retorno do intervalo") → Foto (contagem de 3 s, ou "Tirar agora") → Registrada (NSR, código curto; volta à espera em 8 s).
- **Leitura do QR:** `BarcodeDetector` quando o navegador tem; senão `jsQR` sobre quadros reduzidos. Só aceita QR do Ponto (crachá impresso ou rotativo do aplicativo); outros são ignorados com aviso.
- **Privacidade na tela:** o CPF/código digitado some depois de 3 s parado (ficam os 3 últimos dígitos); erro de identificação sempre com a mesma mensagem; a tela volta ao início após 30 s sem toque.
- **Foto obrigatória:** câmera negada, ausente ou lenta = erro com orientação (usar o aplicativo ou procurar o RH); nada é registrado sem foto. O local (GPS do aparelho) é pedido em paralelo e enviado se disponível; sem GPS a batida segue.
- **Aparelho:** mostra "Sem conexão" e desativa as ações (a central não funciona sem internet nesta versão); tenta manter a tela ligada (`wakeLock`) e tem botão de tela cheia. Layout em `vmin`: funciona em tablet na horizontal e na vertical.
- **Verificado no navegador** (câmera simulada por um `canvas`; o QR foi gerado de verdade e decodificado pelo `jsQR`): pareamento, código, PIN errado e certo, QR, consentimento, foto e batida, revogação e o layout vertical. **Não verificado em tablet real** (câmera física, GPS, tela cheia, `wakeLock`, instalação como app).

## Central do Ponto: Gestão (fase 2)

- **Gestão > Centrais** (administrador; RH e auditor só veem): lista das centrais com situação (aguardando pareamento, pareada, revogada), última vez vista, batidas de hoje, raio e posto; alerta se uma central pareada não dá sinal há mais de 1 h. **Cadastrar uma central** (nome, latitude/longitude, botão "Usar minha localização atual", raio de 100 m por padrão) mostra o **código de pareamento uma única vez**, com o endereço `/central` a abrir no tablet. Também: novo código de pareamento e revogar, ambos com confirmação na tela. Até 5 centrais ativas por empresa.
- **Exigir PIN na Central** (administrador): caixa de marcar na mesma aba (padrão desligado), com o aviso de que sem PIN o código ou o CPF sozinho identifica. A foto é sempre obrigatória.
- **Gestão > Pessoas > pessoa:** mostra o **código interno** e se há PIN; botões **Baixar crachá (PDF)**, **Zerar PIN** e **Regenerar crachá** (confirmação avisando que o QR impresso deixa de valer). No alto da lista, **Crachás de todos (PDF)**: 8 cartões por A4 (nome, cargo, código interno e QR assinado); RH não imprime crachás de RH, administrador e auditor. Cada impressão vai para a auditoria (`badge_print`).
- **Auditoria:** os eventos da Central têm nomes legíveis (Central pareada, Batida na Central, Zerou o PIN, Regenerou o crachá…) e há filtro por `kiosk`.
- **API nova:** `GET /users/{id}/badge.pdf`, `GET /badges.pdf?ids=...`; `GET /kiosks` devolve `punches_today`.
- **Verificado no navegador:** cadastro de central e código de pareamento, exigir PIN, revogação, código e ações do crachá na pessoa. O PDF dos crachás foi renderizado e conferido visualmente. **Não verificado:** impressão em papel e leitura do QR impresso por uma câmera real.

## Central do Ponto: colaborador (fase 4)

- **Minha conta > Central do Ponto:** mostra o **código interno** (oculto até tocar em "Mostrar") e se há PIN; **Definir/Trocar o PIN** (4 a 6 dígitos, sem sequências óbvias, pede a senha atual); **Meu crachá (QR)**: tela cheia com QR rotativo (troca a cada 30 s, contagem regressiva), para a câmera da Central ler.
- **Origem da batida:** `GET /punches` devolve `origin` ("Aplicativo" ou "Central <nome>") e a lista de comprovantes em Espelho mostra a origem.
- **Política por pessoa** (Gestão > Pessoas > pessoa > "Bate ponto em"): *Aplicativo e Central* (padrão) ou *Só a Central*. Nesta última o `POST /punches` responde 403, o botão do app fica desativado com a explicação e a Central continua funcionando. Migração `0009`.
- **Verificado no navegador:** PIN fraco recusado, PIN válido salvo, QR rotativo na tela, botão bloqueado na política "só Central". **Não verificado:** o seletor de política em Pessoas (só compilado e coberto pela API), leitura desse QR por uma câmera real.

## Central do Ponto: relatórios e importação (fase 5)

- **Relatórios > Batidas por origem** (`GET /reports/punches?start&end&origin=all|app|central&format=csv|pdf`): cada marcação (NSR) do período no escopo de quem emite, com origem ("Aplicativo" ou "Central <nome>"), se foi sem internet e a distância ao posto. Máximo de 93 dias.
- **Relatórios > Divergências da Central** (`GET /reports/kiosk-divergences`, só RH, administrador e auditor): batidas **fora do posto** (distância maior que o raio) ou **sem localização**, **falhas de identificação** por central e dia, e aparelhos **sem sinal** há mais de 1 h. Nada disso bloqueia a batida.
- **Importação CSV:** coluna opcional `codigo` (também `matricula`), de 4 a 10 números, única na empresa; se vazia, o sistema gera. O modelo de planilha inclui a coluna.
- **AFD/AEJ:** o coletor `04` (Central) já vai no campo de coletor de cada marcação. **Não feito:** origem no Espelho de Ponto em PDF (documento oficial, layout sujeito à homologação).
- **Verificado:** testes de backend (filtro por origem, divergências, permissões, PDF, código no CSV). A tela de Relatórios foi só compilada e testada por unidade, não aberta no navegador.

## Central do Ponto: leitor USB/Bluetooth (fase 6, parcial)

Leitores em modo teclado (padrão de fábrica) funcionam na espera e na tela do QR: a leitura rápida de um QR do Ponto identifica a pessoa. Testado só por unidade; falta um leitor real. **Central sem internet (opção C):** só o QR do crachá impresso vale; a batida (QR, foto, hora, posição) fica na fila do aparelho e o servidor confere tudo no envio (`POST /kiosk/offline-punch`); recusas vão para a auditoria e para Divergências da Central. Desligada se a empresa exige PIN. Detalhes e limites em `docs/central-do-ponto.md` (seção 8). NFC não foi feito.

## Pessoas, funções e áreas do aplicativo

Cada pessoa tem três escolhas independentes, todas no mesmo formulário (Gestão > Cadastros > Pessoas, para cadastrar e para editar):

- **Registra ponto**: a pessoa está sob controle de jornada (espelho, banco de horas, ajustes). Desmarcado = cadastro só de gestão.
- **Entra no aplicativo**: desmarcado = só bate ponto na Central, sem e-mail nem senha. Quem tem função de gestão ou não registra ponto precisa entrar.
- **Funções de gestão** (acumuláveis, só a Administração atribui): **Administração** (perfil mestre: empresa, configurações, centrais, permissões, auditoria, e tudo do RH e do Gestor), **RH** (cadastros, jornadas, ausências, banco de horas, fechamento, relatórios e arquivos fiscais da empresa toda) e **Gestor** (a própria equipe: painel, espelhos e aprovações). O campo "Gestor" de cada pessoa só aceita quem tem uma dessas funções.

O aplicativo tem duas áreas: **Meu ponto** (Ponto, Registros, Solicitações, Banco de horas), para quem registra ponto, e **Gestão** (Painel, Aprovações, Espelhos, Banco de horas, Ausências, Relatórios, Cadastros, Empresa), para quem tem alguma função. Quem tem as duas troca pelo seletor no topo. A regra de quem pode o quê fica em `backend/app/permissions.py` e é a mesma para a API e para as telas (`/auth/me` devolve as permissões).

Autoaprovação: a Administração só decide o próprio pedido quando ninguém mais na empresa poderia decidi-lo, com justificativa obrigatória (fica como `self_approve` na auditoria).

## Editar e excluir cadastros

- **Pessoas:** "Editar dados" (nome, e-mail, CPF, cargo). O CPF só muda enquanto a pessoa não tem marcações; nome e CPF alterados vão para o REP-P (tipo 5). "Excluir cadastro" só vale para quem nunca teve marcações, ajustes, ausências, banco de horas ou fotos (cadastro por engano; gera o evento de exclusão tipo 5). Quem já trabalhou é **desativado**, o que mantém o histórico.
- **Jornadas:** edição completa. Só o nome muda sem efeito no cálculo; as demais mudanças são recusadas se um mês fechado tiver marcações de pessoas da jornada. Exclusão só de jornada que ninguém usa.
- **Centrais:** edição de nome, posto e raio; exclusão só depois de revogada (as batidas continuam nos registros).
- Tudo na auditoria. O papel `ponto_app` ganhou `DELETE` só em `users`, `schedules`, `kiosks` e `kiosk_tickets` (reaplicado pelo `dbinit` a cada subida).

## Piloto e implantação

Roteiro em fases (preparação, ensaio, piloto de um mês, expansão), com lista de testes práticos, ficha do tablet da Central, métricas, contingência e pendências legais: [docs/piloto-e-implantacao.md](docs/piloto-e-implantacao.md).

## Foto opcional na batida

Ativada por empresa (Gestão > Fechamento, só o administrador) e consentida por pessoa (LGPD). Se a pessoa recusa, a câmera falha, demora mais de 6 s ou o armazenamento do aparelho enche, o ponto é registrado do mesmo jeito: **a batida nunca depende da foto**.

- **Fluxo:** "Registrar ponto" abre a câmera frontal; "Tirar foto e registrar" (ou "Registrar sem foto"). A batida é gravada primeiro e a foto é enviada em seguida (`POST /punches/{id}/photo`, JPEG até 400 KB, reduzido a 640 px no aparelho). Sem internet, a foto vai junto da marcação na fila e é enviada com ela.
- **Fora do ARP:** a foto não entra no hash da marcação nem no AFD/AEJ. Fica na tabela `punch_photos` (mutável de propósito: única tabela com DELETE, ver `deploy/postgres-roles.sql`) e criptografada em disco (Fernet, chave derivada de `PONTO_SECRET_KEY`).
- **Acesso:** só RH e administrador (`GET /punches/{id}/photo`, `GET /photos?user_id&month`), na tela Registros ao ver outra pessoa. Cada consulta vai para a auditoria (`view_photo`). Gestor e colaborador não veem.
- **Retenção:** as fotos de um mês são apagadas (arquivo e registro) quando o mês é **fechado** (`purge_photos` na auditoria). Reabrir o mês não as traz de volta, e não se pode anexar foto a mês fechado. As marcações nunca são apagadas. Um mês que ninguém fecha mantém as fotos: feche os meses em dia.
- **O que não é:** não há reconhecimento facial nem detecção de "prova de vida"; a foto é evidência para uma pessoa conferir. Não substitui biometria.
- **Armazenamento:** `services/photos.py` define a interface `PhotoStore` (`put/get/delete`) com duas implementações: pasta local (`PONTO_PHOTO_DIR`, padrão) e bucket S3-compatível (`PONTO_PHOTO_STORE=s3`, ver abaixo).

### Configurar o bucket S3-compatível (privado)

`PONTO_PHOTO_STORE=s3` troca a pasta local por um bucket. Funciona com AWS S3, Cloudflare R2, Backblaze B2 e MinIO (mesma configuração, só muda o endereço). As fotos vão **duas vezes cifradas**: pela aplicação (Fernet) e pelo servidor do bucket (`S3_SSE`); o bucket nunca guarda a imagem pura. Não há URL pública: quem vê a foto é sempre a API, depois de conferir o perfil.

1. **Crie o bucket privado** na região do Brasil quando o provedor tiver (AWS: `sa-east-1`). Ligue "bloquear todo acesso público" e não crie nenhuma política pública.
2. **Crie uma credencial só para o Ponto**, restrita a esse bucket e ao prefixo `fotos/`, com apenas estas permissões: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` (não dê listagem nem administração). Exemplo de política (AWS):
   ```json
   {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"], "Resource": "arn:aws:s3:::NOME-DO-BUCKET/fotos/*"}]}
   ```
   Em R2/B2, gere uma chave de API com escopo "Object Read & Write" limitada a esse bucket.
3. **Regra de expiração (rede de segurança):** no bucket, apague objetos com prefixo `fotos/` após ~45 dias. O fechamento do mês continua sendo quem apaga; a regra só limita o pior caso (mês esquecido aberto).
4. **Preencha o `.env`** (`PHOTO_STORE=s3`, `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` se não for AWS, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`; MinIO: `S3_PATH_STYLE=true`). Na AWS, se a VM tiver um papel IAM, deixe as chaves vazias.
5. **Teste antes de usar:** `docker compose exec app python -m app.photos_check` grava, lê e apaga um objeto de teste e diz o que está errado (bucket inexistente, credencial sem permissão, endereço errado).
6. **Guarde a `SECRET_KEY`** (ou `TOTP_KEY`): ela deriva a chave que cifra as fotos. Sem ela, as fotos já guardadas não abrem (o que, para fotos de vida curta, é tolerável, mas as marcações continuam intactas).

**Retenção com bucket fora do ar:** o fechamento do mês não falha; as fotos que não puderam ser apagadas ficam registradas e são apagadas na varredura do próximo fechamento (a auditoria mostra `pending`).

### Opções de guarda na nuvem
| Opção | Prós | Contras |
| --- | --- | --- |
| **Bucket S3-compatível** (AWS S3, Cloudflare R2, Backblaze B2, MinIO) | Padrão de mercado, barato, uma única biblioteca (boto3) serve para todos, regra de ciclo de vida como segunda rede de segurança | Precisa de credenciais e política de acesso |
| **Azure Blob Storage** | Bom se a empresa já usa Azure/Microsoft 365 | SDK próprio |
| **Google Cloud Storage** | Bom se já usa GCP | SDK próprio |
| **Disco/volume da própria VM** (o que existe hoje) | Nada a contratar | Vive e morre com a VM; sem redundância |

Recomendação: bucket S3-compatível, **privado**, criptografia no servidor ligada além da criptografia da aplicação, região no Brasil (LGPD), acesso só pela aplicação (sem URL pública), e uma regra de expiração (por exemplo 45 dias) como rede de segurança caso um mês não seja fechado. O prazo do fechamento continua mandando; a regra do bucket só limita o pior caso.

## App instalável e uso sem internet (PWA)

O service worker (`frontend/public/sw.js`) guarda o app **inteiro** na instalação: o build (`vite.config.ts`) grava nele a lista de todos os arquivos (JS, CSS, fontes) e uma versão; versão nova troca o cache antigo. Sem rede (ou com rede travada por mais de 4 s) a navegação serve a página guardada, e as consultas de sessão, empresa, marcações, espelho, ajustes, ausências e banco de horas usam o último dado guardado. `/api/time` nunca é guardado. Requer HTTPS (ou localhost) e uma primeira abertura com internet.

**Roteiro de teste (Chrome, com o app em HTTPS ou localhost):**
1. Abra o app, entre e navegue por Ponto e Registros com internet. DevTools > Application > Service Workers: deve estar "activated"; Cache Storage: `ponto-shell-<versão>` com os arquivos de `/assets`.
2. Instale (menu > Instalar app) e feche a aba.
3. DevTools > Network > Offline (ou modo avião). Abra o app pelo ícone: deve abrir logado, com o relógio e o histórico do dia.
4. Registre ponto sem internet: aparece "Guardado — aguardando envio". Volte a internet: em até 30 s a marcação é enviada e ganha NSR.
5. Publique uma versão nova (`npm run build`), recarregue duas vezes com internet: o cache `ponto-shell-*` antigo some.

**Limites conhecidos:** no iPhone, o Safari pode apagar os dados de sites pouco usados e não envia em segundo plano com o app fechado; um app nativo embrulhado (Capacitor) resolve isso, se necessário. Entrar (login) exige internet. Esta rodada **não foi verificada em navegador real**: o navegador embutido do desenvolvimento não registra service workers.

## Rodar localmente para testar

`run-local.ps1` sobe tudo em http://localhost:8765 (SQLite, modo de teste). `-Reset` apaga o banco de teste antes de subir; `-Demo` (banco vazio, use com `-Reset`) cria a empresa demo com RH, gestor, 3 colaboradores, ~3 semanas de marcações relativas a hoje, um ajuste e uma ausência pendentes, e férias aprovadas. Logins: admin@demo.com, rita@demo.com (RH), gil@demo.com (gestor), ana@demo.com, beto@demo.com, carla@demo.com; senha `senha-forte-123`. Sem `-Demo`, cria só `admin@teste.com`. O `-Reset` só toca no SQLite deste script.

## Registro de ponto: um botão só

**Máximo de 4 batidas por jornada.** A saída é definitiva: depois dela o botão fica desativado ("Jornada encerrada") e o servidor recusa outra batida (409, `punching.day_closed`). Correções só por Ajustes. O comprovante não aparece logo após o registro: fica em "Hoje" e em Registros > "Comprovantes das últimas batidas".

**Jornada encerrada à meia-noite (padrão) ou turno que vira a noite.** Por padrão cada jornada se encerra à meia-noite: uma entrada sem saída no dia vira "saída ausente" (o Espelho mostra o dia como incompleto, o painel como "saída não registrada" e a correção é por Ajustes), o dia seguinte recomeça em **entrada**, e a saída do dia seguinte não é pareada com a entrada de ontem. Ao criar a jornada (Gestão > Jornadas) dá para ligar "A jornada pode terminar no dia seguinte (turno da noite)": aí o turno aberto continua após a meia-noite (limite de 16 h), a saída da madrugada fecha o turno do dia anterior e a hora noturna e o "(dia seguinte)" funcionam como antes. Quem não tem jornada atribuída segue o padrão (encerra à meia-noite). A opção pode ser alterada depois em Gestão > Jornadas (`PATCH /schedules/{id}`), com confirmação na tela e auditoria do antes e depois; como o Espelho é calculado das marcações, a mudança vale também para dias já passados ainda abertos. **É recusada (409) se houver mês fechado com marcações de pessoas dessa jornada**: reabra o mês antes (RH ou administrador). A mesma proteção vale para **trocar a jornada de uma pessoa** (`PATCH /users/{id}` com outro `schedule_id`): recusada (409) se houver mês fechado com marcações dela; repetir a mesma jornada ou mudar outros campos não é troca. Na tela: Gestão > Pessoas > tocar na pessoa > campo "Jornada"; a troca pede confirmação e mostra a recusa dentro da própria caixa. A regra está no servidor (`punching.py`, `timecalc.py`, `espelho.py`, `panel.py`) e espelhada na tela (`frontend/src/sequence.ts`). A linha do tempo "Hoje" mostra o turno em andamento, não o dia do calendário.

A tela de ponto tem **um botão** ("Registrar ponto"); o tipo da marcação vem da **ordem**: entrada, início do intervalo, fim do
intervalo, saída (jornada sem intervalo: entrada e saída). O servidor decide (`punching.next_kind`); a tela espelha a regra
(`frontend/src/sequence.ts`) para funcionar sem internet, e `GET /punches/next` informa se a jornada tem intervalo. Quem vai embora
sem fazer o intervalo usa o link "Vou embora sem fazer o intervalo" (marca `saida` explicitamente). Marcação aberta há mais de 16 h
recomeça em entrada. Erro de sequência (esquecimento) corrige-se por Ajustes, como antes. O comprovante fica recolhido após o registro.

**Visual:** segue o `design.md` (fontes Space Grotesk/Public Sans empacotadas localmente, por causa da CSP; tokens claro/escuro com
alternância manual; cabeçalho com marca, tema e avatar; barra inferior de 4 abas no celular com os demais itens em "Mais"; menu
horizontal completo a partir de 768 px). **Espelho:** resumo do mês (trabalhadas, previstas, saldo), filtro "Dias úteis / Pendências / Todos" (folgas e dias futuros ficam ocultos por padrão), dia em uma linha com as horas e detalhe ao tocar, atalho "Pedir ajuste deste dia". **Ajustes:** "Esqueci de bater" / "Bati por engano", justificativas rápidas, rejeição com motivo na própria tela; o aprovador vê quem pediu e qual marcação seria desconsiderada (`GET /adjustments` devolve `user_name`, `target_kind`, `target_at`).
**Equipe:** linhas com avatar, situação (ponto colorido), atraso e banco de horas; faixa de pontos de atenção (ajustes a aprovar, atrasados, alertas); linha inteira abre o Espelho. **Ausências:** tipo e duração por seletores, rejeição e cancelamento confirmados na tela (sem caixas do navegador), formulário do RH recolhido. **Banco de horas:** saldo em destaque, extrato em lista, lançamento do RH e regras do administrador recolhidos.
**Gestão:** abas roláveis; Pessoas em lista com busca e ações por pessoa (banco de horas, nova senha, zerar 2FA, desativar) confirmadas na tela, cadastro e importação CSV recolhidos; Jornadas em cartões (dias como chips); Fechamento com reabertura confirmada na tela; Auditoria em lista legível; Fiscalização com o aviso de pendências no topo.
**Relatórios:** um cartão por relatório (PDF em destaque, planilha CSV ao lado), datas padrão no fuso da empresa e aviso de arquivo gerado. **Minha conta:** cartão de perfil, troca de senha recolhida (aberta quando a senha é temporária) e 2FA em cartão próprio.
**Saudação e batidas:** a tela de ponto mostra, entre a barra superior e o cartão de registro, 'Bom dia/Boa tarde/Boa noite, <nome>' pelo horário da empresa; as batidas são numeradas (1ª Entrada, 2ª Intervalo, 3ª Retorno do intervalo, 4ª Saída; sem intervalo na jornada: 1ª Entrada, 2ª Saída) e a tela diz qual é a próxima ('Próxima batida: 3ª · Retorno do intervalo'). Os tipos gravados (AFD/AEJ) não mudam, só os nomes exibidos.
**Coluna lateral do desktop** (a partir de 768 px, grade 1fr + 340 px): "Esta semana" (horas trabalhadas de segunda a domingo em barras, total contra o previsto; o dia em andamento em tom claro) e, para gestor/RH/administrador, "Equipe" com ponto de situação por pessoa. No celular a equipe vira uma faixa de chips (ponto + primeiro nome) sob a saudação e o resumo semanal não aparece. Dados de `GET /mirror` e `GET /dashboard`, atualizados a cada batida. O turno em andamento entra no gráfico e no total (o servidor só conta jornadas encerradas): os minutos desde a última entrada ou retorno são somados no dia em que o turno começou e a barra fica em tom claro até a saída; em intervalo o tempo não corre.
gráfico semanal.

## Registro sem internet

O colaborador pode marcar ponto sem rede; a marcação fica na fila do aparelho e é enviada quando a conexão volta.

- **Hora:** o app mede o desvio entre o relógio do aparelho e o do servidor (`GET /time`) sempre que há rede e guarda a medida.
  Sem rede, a hora da marcação é `relógio do aparelho + desvio`. O aparelho **não** marca sem rede se nunca mediu o desvio, se a medida
  tem mais de 7 dias ou se o relógio voltou no tempo depois dela.
- **Servidor** (`POST /punches` com `offline=true`): exige `client_key`, `occurred_at` e `kind`; recusa hora no futuro (>2 min) e
  marcação com mais de `PONTO_OFFLINE_MAX_HOURS` (padrão 72 h; depois disso só por ajuste aprovado). Marcação online continua usando
  só a hora do servidor. `PONTO_OFFLINE_PUNCH_ENABLED=false` desliga o recurso.
- **Registro:** NSR e `recorded_at` são os do momento do envio; o campo off-line (posição 1 do registro 7 do AFD) vai como `1` e entra
  no hash. Auditoria guarda a hora crua do aparelho, o desvio usado e o atraso do envio. O Espelho marca "(off-line)".
- **Sequência:** a marcação é validada contra a que vem *antes* dela no tempo. Recusa definitiva (sequência, prazo, mês fechado) vira
  "não aceita" na tela, com o caminho de ajuste; falhas de rede/servidor mantêm a fila e tentam de novo (ao voltar a rede, ao abrir o
  app e a cada 30 s). Reenvio é idempotente (`client_key`), inclusive depois do prazo.
- **Comprovante:** o do Art. 79/80 só existe depois do envio (precisa do NSR); no aparelho aparece um protocolo provisório, dito não oficial.
- **Limites:** a hora off-line depende do relógio do aparelho (mitigada pelas travas acima e pela auditoria; um aparelho adulterado
  *dentro* dessas travas não é detectável). A fila fica em `localStorage`: limpar os dados do navegador antes do envio a perde. Não
  há envio em segundo plano com o app fechado (Background Sync); envia ao reabrir. **Hipótese H7:** o texto do Anexo IX sobre off-line
  precisa ser confirmado com a área jurídica/homologação (uso "excepcional", conteúdo do comprovante).

## Relatórios gerenciais

`GET /reports/monthly?month=AAAA-MM`, `/reports/hour-bank` e `/reports/absences?start=&end=&status=`, cada um com `format=csv|pdf`
(tela **Relatórios**, ligada em Equipe e Gestão). Os números vêm do mesmo cálculo do Espelho, sem recalcular. Gestor: a própria equipe;
RH, administrador e auditor: a empresa; colaborador: 403. Motivo de atestado e afastamento (dado de saúde) só sai para RH/admin;
para os demais aparece "(restrito)". CSV com `;`, BOM UTF-8 e proteção contra injeção de fórmula (`=`, `+`, `-`, `@` viram texto).
Máximo de 500 pessoas por emissão. Toda emissão vai para a auditoria (sem conteúdo). **Não substituem** o Espelho oficial (Art. 84).

## Contas, senhas e 2FA

- **Senha inicial temporária:** quem o RH cadastra (ou importa) recebe uma senha temporária de 12 caracteres e é obrigado a
  trocá-la no primeiro acesso: até lá o servidor só libera `/auth/me` e a troca de senha. Política: 10+ caracteres com letras
  e números, sem o e-mail nem o CPF, diferente da atual.
- **Sessões:** cada usuário tem uma `token_version` dentro dos tokens. Trocar a senha, redefinir a senha, ativar/desativar o
  2FA ou zerar o 2FA derruba as outras sessões (a que fez a troca continua, com token novo).
- **2FA (TOTP, RFC 6238):** aplicativo autenticador + 8 códigos de recuperação de uso único (só o hash é guardado). Cada
  código vale uma vez (anti-repetição por passo de 30 s, tolerância de ±1 passo). O segredo fica **cifrado** no banco (Fernet;
  chave em `PONTO_TOTP_KEY`, padrão derivada de `PONTO_SECRET_KEY`). Código errado conta para o limite de tentativas de login.
- `PONTO_REQUIRE_2FA_ROLES=hr,admin` obriga esses perfis a ter 2FA: sem ele, a conta só acessa a tela de configuração.
- **Redefinição pelo RH/admin:** nova senha temporária (`POST /users/{id}/reset-password`) e remoção do 2FA
  (`POST /users/{id}/reset-2fa`); o RH não mexe em contas de RH, admin e auditor (só o administrador). Ambas vão para a
  auditoria (sem senhas nem códigos).
- **Importação CSV** (`POST /users/import`, Gestão → Colaboradores): colunas `nome`, `email`, `cpf` (obrigatórias), `cargo`,
  `gestor` (e-mail), `jornada` (nome), `perfil`, `admissao`. Aceita UTF-8 e o CSV do Excel em português (Windows-1252, `;`).
  **Valide antes** (`dry_run=true`, o padrão): nada é gravado. A importação grava tudo ou nada (até 200 linhas por causa do
  custo do hash das senhas) e mostra as senhas temporárias **uma única vez**. Cada inclusão vira registro tipo 5 no ARP.

## Ausências justificadas

- **Tipos:** atestado médico e abono (o colaborador pede; o gestor da equipe ou o RH aprova) e férias, licença e
  afastamento INSS (**só o RH registra**, já aprovados). Atestado e abono podem ser parciais (em horas, um único dia).
- **Efeito:** dia inteiro justificado sem marcações deixa de ser falta (`justificada`), sem saldo negativo e sem entrar no
  AEJ como falta não justificada. Se a pessoa trabalhou no dia, a jornada esperada é zero e tudo vira saldo. Justificativa
  parcial reduz a jornada esperada, mas só vale se houve marcações (sem nenhuma marcação continua sendo falta). Fins de
  semana e folgas continuam folga. O banco de horas usa a jornada reduzida; o painel mostra "Ausência justificada"; o
  Espelho oficial traz o motivo na coluna Situação.
- **Privacidade (LGPD, dado de saúde):** o motivo e o anexo de atestado e de afastamento INSS só o dono e o RH/admin veem;
  o gestor vê o fato e o período ("Motivo restrito ao RH"). O motivo **não** vai para a trilha de auditoria. Peça ao
  colaborador que não informe diagnóstico nem CID.
- **Regras:** colaborador pede até 90 dias atrás (o RH não tem esse limite); período de até 366 dias; sobreposição é
  recusada; mês fechado não recebe, não aprova e não cancela ausência; ausência **pendente bloqueia o fechamento** do mês.
  Ninguém aprova a própria ausência. O RH cancela também as aprovadas, enquanto o mês estiver aberto.
- **Limite conhecido:** ainda não há envio de arquivo (o campo de anexo guarda só o nome); o comprovante original é
  entregue ao RH. Isso depende de escolher onde armazenar arquivos (ver infraestrutura).

## Painel do gestor e banco de horas

- `GET /api/dashboard[?at=<UTC>&bank=true]` (gestor: a equipe; RH/admin: a empresa): estado de cada pessoa em um instante
  (presente, em intervalo, saiu, sem marcação, saída não registrada, ainda não iniciou, folga), atraso além de 5 min
  (CLT art. 58 §1º), tempo trabalhado no dia e pendências. `at` só aceita presente ou passado. O estado usa apenas
  as marcações reais do REP (marcações desconsideradas não contam; ajustes não mudam quem "está aqui").
- **Banco de horas** é ativado por colaborador (Gestão → Colaboradores); o saldo conta da data de início.
  Saldo = saldo diário automático (depois da tolerância, só dias com jornada concluída) + créditos − compensações do RH.
  **Faltas de dia inteiro não entram sozinhas**: descontá-las do banco é decisão do RH, via compensação.
  Lançamentos do RH (`POST /api/hour-bank/entries`) são append-only (ORM, gatilhos e papel restrito): corrige-se
  com o lançamento contrário. Compensação maior que o saldo é recusada; mês fechado não recebe lançamento.
- Regras por empresa (administrador): `bank_max_minutes` (alerta acima do limite) e `bank_expiry_months`
  (alerta de saldo positivo com mais tempo que o prazo, por estimativa: o que já existia na data de corte e continua no saldo).
  O prazo legal depende do instrumento (acordo individual ou coletivo): confirmar com a assessoria jurídica.
- O AEJ passa a trazer os movimentos do banco (registro 07, tipo 3: 1 = inclusão, 2 = compensação).
- Limite conhecido: o saldo é recalculado a partir do início do banco a cada consulta (sem cache); adequado para
  dezenas de colaboradores; para centenas, materializar o saldo mensal ao fechar o mês.

## Conformidade REP-P (Portaria MTP 671/2021)

O sistema segue o leiaute da Portaria (texto oficial no DOU, Anexos V, VI e IX). Para emitir arquivos válidos é
preciso configurar (aba **Gestão → Fiscalização** mostra o que falta):

| Variável | Para quê |
| --- | --- |
| `PONTO_INPI_NUMBER` | Nº do registro do programa no INPI (Art. 91), até 17 dígitos. Sem ele o AFD/AEJ não são gerados |
| `PONTO_ALLOW_MISSING_INPI=true` | **Modo de teste** (só desenvolvimento): gera AFD/AEJ sem INPI e sem identificação do desenvolvedor, usando zeros. Os arquivos não valem para fiscalização; a resposta traz o cabeçalho `X-Ponto-Warning` e a tela de Fiscalização mostra "MODO DE TESTE". Desligado por padrão: sem a variável, a geração é recusada |
| `PONTO_DEV_ID`, `PONTO_DEV_NAME`, `PONTO_DEV_EMAIL` | CNPJ/CPF, nome e e-mail do desenvolvedor (cabeçalho do AFD e registro 08 do AEJ) |
| `PONTO_SIGNING_P12_PATH`, `PONTO_SIGNING_P12_PASSWORD` | Certificado ICP-Brasil (PKCS#12) para assinar os arquivos (Art. 88) |
| `PONTO_CLOCK_CHECK_ENABLED=true` | Recusa marcações se o relógio do servidor divergir mais de 30 s do NTP (`PONTO_NTP_SERVER`, padrão `a.st1.ntp.br`), conforme Anexo IX, item 2 |

- `GET /api/exports/afd?start=AAAA-MM-DD&end=AAAA-MM-DD` e `/api/exports/aej?...` (RH, admin e auditor);
  `&signed=true` devolve um `.zip` com o arquivo e a assinatura destacada `.p7s`.
- **ARP** (`punches` + `arp_events`): uma única sequência de NSR por empresa para todos os tipos de registro
  (2 empregador, 5 empregado, 6 eventos do serviço, 7 marcação). Tudo append-only.
- **Ajustes não alteram o ARP:** inclusão manual e desconsideração são tratamento e só aparecem no AEJ
  (fonte "I" e tipo "D"); não geram marcação nem consomem NSR.

### Hipóteses de interpretação (a Portaria não especifica; **validar na homologação**)

| # | Ponto | O que foi adotado | Onde mudar |
| --- | --- | --- | --- |
| H1 | Hash da marcação (SHA-256) | Concatenação sem separador dos campos do registro 7 como no AFD (NSR 9 + "7" + DH marcação + CPF 12 + DH gravação + coletor + off-line + hash anterior), hex minúsculo | `services/arp.py::punch_hash` |
| H2 | "Hash do registro anterior" | Hash da marcação (tipo 7) anterior do estabelecimento; vazio na primeira | `services/arp.py` |
| H3 | Preenchimento dos campos | Numéricos com zeros à esquerda; alfanuméricos com espaços à direita (o texto diz apenas "completar com espaço") | `services/layout.py` |
| H4 | CRC-16 | CRC-16/ARC (0xA001, inicial 0) sobre o registro sem o campo do CRC, hex maiúsculo | `services/layout.py::crc16` |
| H5 | Assinatura dos arquivos | CMS/PKCS#7 destacada (`.p7s`, SHA-256), sem atributos de política ICP-Brasil; o registro "assinatura digital" de 100 posições do anexo não é gravado no arquivo | `services/signing.py` |
| H6 | Assinatura do PDF | PAdES (`ETSI.CAdES.detached`) incremental via pyHanko, SHA-256; sem política ICP-Brasil (DOC-ICP-15) nem carimbo do tempo | `services/pdfsign.py` |
| H7 | Registro off-line | Hora = relógio do aparelho + desvio medido; NSR/gravação no envio; campo off-line = 1; prazo de 72 h; sem comprovante antes do envio | `routers/punches.py`, `frontend/src/offline.ts` |

**PDFs (Art. 79/80 e 84):** `GET /api/punches/{id}/receipt.pdf` (comprovante assinado; sem certificado só em modo de
teste, e então vem marcado "DOCUMENTO DE TESTE") e `GET /api/mirror/official.pdf?month=AAAA-MM[&user_id=]` (Espelho de
Ponto Eletrônico com empregador, trabalhador, admissão, cargo/função, horário contratual, marcações do REP e tratadas
e duração com hora noturna reduzida). Turnos que atravessam a meia-noite aparecem no dia em que começaram.

Ainda **não** implementado nesta área: registro 07 do AEJ para DSR e banco de horas, matrículas do
eSocial (registro 06), pré-assinalação de intervalo e o Atestado Técnico (Anexo VII, documento do desenvolvedor).

## Testes

```bash
cd backend && pip install -r requirements-dev.txt && ruff check . && python -m pytest   # SQLite; testes de PostgreSQL são pulados
cd frontend && npm test && npm run build          # utilitários + checagem de tipos
```

Para rodar também os testes de PostgreSQL (concorrência do NSR, gatilhos, migrações, papel restrito), aponte
`PONTO_TEST_DATABASE_URL` para um banco **descartável** (a suíte apaga as tabelas dele). Sem Docker, dá para
subir um cluster temporário com as ferramentas do PostgreSQL instalado:

```bash
initdb -D /tmp/pgtest -U ponto --auth=trust -E UTF8 --locale=C
pg_ctl -D /tmp/pgtest -o "-p 5544 -c listen_addresses=127.0.0.1" start
psql -h 127.0.0.1 -p 5544 -U ponto -d postgres -c "create database ponto_test"
export PONTO_TEST_DATABASE_URL=postgresql+psycopg://ponto@127.0.0.1:5544/ponto_test
```

## Estado atual (MVP em construção)

| Área | Situação |
| --- | --- |
| Login, refresh, perfis (RBAC), isolamento entre empresas | Pronto e testado |
| Empresas, colaboradores (com data de admissão), jornadas | Pronto (falta importação CSV) |
| Registro de ponto: hora do servidor, NSR sequencial, hash encadeado, idempotência, consentimento GPS | Pronto e testado |
| NSR sem lacunas sob concorrência | **Provado em PostgreSQL** (8 conexões simultâneas; sem o `FOR UPDATE` o teste falha com NSR duplicado) |
| Imutabilidade de marcações e auditoria | Pronto e testado em SQLite e PostgreSQL (ORM + gatilhos + papel restrito) |
| Verificação de integridade da cadeia (RF-29) | Pronto e testado |
| Migrações Alembic | Pronto; testadas em SQLite e PostgreSQL (upgrade, downgrade, ciclo repetido, sem divergência do modelo) |
| Espelho, ajustes com aprovação (tratamento, fora do ARP), fechamento/reabertura, trilha de auditoria | Pronto e testado |
| ARP conforme a Portaria: NSR único por empresa, hash SHA-256 da marcação (H1), CPF, fuso, coletor, eventos tipos 2/5/6 | Pronto e testado (hash recalculado de forma independente nos testes) |
| AFD (Anexo V, leiaute 003) e AEJ (Anexo VI): posições, tamanhos, CRC, trailer, ISO 8859-1 com CRLF | Pronto e testado; **hipóteses H1–H6 a validar** |
| Assinatura destacada dos arquivos (.p7s) | Pronta e testada com certificado de teste e OpenSSL; falta certificado ICP-Brasil real |
| Sincronismo com a Hora Legal Brasileira (NTP, 30 s) | Pronto e testado com NTP simulado; não testado contra `a.st1.ntp.br` |
| Comprovante (Arts. 79 e 80): dados completos, últimas 48 h e **PDF assinado (PAdES)** | Pronto e testado (assinatura validada de forma independente; adulteração detectada); falta certificado ICP-Brasil real |
| Espelho de Ponto Eletrônico oficial (Art. 84) em PDF, com cargo/função, hora noturna reduzida e marcações tratadas | Pronto e testado; PDF inspecionado visualmente |
| PWA: login, registrar ponto + comprovante, espelho, ajustes e aprovações, gestão | Pronto; verificado no navegador em celular e desktop |
| PWA offline (service worker) | Escrito, **não verificado**: o navegador embutido do app recusou registrá-lo. Testar em Chrome/Safari reais |
| Painel do gestor (RF-18): presença, intervalo, atraso, sem marcação, saída não registrada, ajustes a aprovar; consulta a qualquer momento passado | Pronto e testado; verificado no navegador |
| Banco de horas (RF-15): saldo automático após a tolerância, lançamentos do RH append-only, extrato, limite e prazo de compensação, movimentos no AEJ (registro 07, tipo 3) | Pronto e testado em SQLite e PostgreSQL |
| Ausências justificadas (RF-13): atestado, abono, férias, licença e afastamento INSS; pedido, aprovação, registro pelo RH, cancelamento; efeito em espelho, banco de horas, painel, fechamento e Espelho oficial | Pronto e testado em SQLite e PostgreSQL; verificado no navegador |
| Importação de colaboradores por CSV (validação linha a linha, tudo ou nada, senhas temporárias) | Pronto e testado; verificado no navegador |
| Senha (troca obrigatória, política, sessões revogáveis) e 2FA TOTP (QR, códigos de recuperação, exigência por perfil, redefinição pelo RH) | Pronto e testado (vetores da RFC 6238); verificado no navegador |
| Relatórios gerenciais em CSV e PDF (fechamento mensal, banco de horas, ausências; escopo por perfil; auditados) | Pronto e testado; PDFs não inspecionados visualmente |
| Envio de arquivo (anexo do atestado) | Pendente (depende de onde guardar arquivos) |
| CI (lint, testes SQLite + PostgreSQL, front, imagem, pilha) e release (GHCR, Trivy, SBOM) | Workflows prontos e validados com `actionlint`; **ainda não rodaram** |
| Implantação (Compose: PostgreSQL + app + Caddy + backup), `dbinit`, runbook | Peças de banco e app verificadas; **Docker e Caddy nunca executados** |
| Backup (retenção, checksum) e restauração com conferência de NSR e hashes | Pronto e testado ponta a ponta em PostgreSQL 18; falta cópia externa automática |
| Logs JSON, `/api/ready`, cabeçalhos de segurança (CSP), limite de login | Pronto e testado (CSP verificada no navegador sem violações) |
| IaC de nuvem, alta disponibilidade, métricas/alertas | Pendente (depende da escolha da nuvem) |
| Registro off-line com sincronização (Anexo IX, itens 4 e 5) | Pronto e testado (API, fila do app, navegador com rede simulada); **não testado em aparelho real** |
| Selfie/geofence | V2 (fora do MVP) |





