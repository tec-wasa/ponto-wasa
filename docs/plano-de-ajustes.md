# Plano de ajustes antes da produção

Revisão feita em 24/11/2026 sobre todas as telas (frontend/src/pages), as rotas da API (backend/app/routers) e as regras de
permissão. Objetivo: cada pessoa ver só o que faz sentido para o papel dela, com uma regra única de permissões, e login com
Google (e Apple).

## 1. Diagnóstico: por que as telas não fazem sentido

O app nasceu com **um perfil por pessoa** (colaborador, gestor, RH, admin) e com a premissa de que **todo mundo bate ponto**.
As mudanças recentes (funções acumuláveis e "Registra ponto") foram encaixadas por cima, sem redesenhar as telas. Resultado:

1. **As telas misturam "o meu ponto" com "a gestão dos outros".** Ajustes, Ausências, Banco de horas e Espelho mostram, na
   mesma página, o formulário pessoal (pedir ajuste, pedir atestado, meu saldo, meus comprovantes) e a parte de gestão
   (aprovar, registrar para outros). Para quem só gere, a metade pessoal é absurda; para quem bate ponto e também aprova,
   a página fica confusa.
2. **A regra de quem vê o quê está espalhada.** O frontend decide por listas de perfis copiadas em 12 lugares
   (`["manager","hr","admin"].includes(user.role)`), e o backend em ~40 (`require_roles(...)`, `actor.role == "manager"`).
   Elas já divergem entre si, e o "Registra ponto" quase nenhuma considera.
3. **O perfil virou um único valor derivado** (`role` = o mais alto da lista). RH + Gestor vira só "RH"; a combinação não
   existe de fato nas regras.
4. **Configurações espalhadas e incompletas**: foto na batida dentro de Fechamento; regras do banco de horas dentro da tela
   Banco de horas; PIN da Central dentro de Centrais; **não há tela para os dados da empresa** (nome, local de trabalho,
   fuso), embora a API aceite.
5. **Textos que pressupõem uma estrutura que a empresa pequena não tem**: "Seu gestor vai avaliar", "O RH pode ativá-lo",
   "procure o RH".

### Inventário das inconsistências encontradas

| # | Onde | Problema |
|---|------|----------|
| 1 | Ausências (`Absences.tsx:119`) | "Pedir atestado ou abono" e "Minhas ausências" aparecem para quem não bate ponto |
| 2 | Ajustes (`Adjustments.tsx:128`) | "Nova solicitação" e "Minhas solicitações" aparecem para quem não bate ponto; para quem aprova, a aprovação divide a página com o pedido pessoal |
| 3 | Minha conta (`Account.tsx:46`) | Bloco "Central do Ponto" (código, PIN, crachá) para quem não bate ponto |
| 4 | Topo do app (`App.tsx:137`) | Aviso "Sem conexão. Você ainda pode registrar ponto" para quem não bate ponto; a fila de batidas offline também roda |
| 5 | Mais (`More.tsx:19`) | Itens fixos (Ajustes, Ausências, Banco) para todos |
| 6 | Banco de horas (`Bank.tsx:72`, `:135`) | "Você não usa banco de horas. O RH pode ativá-lo"; regras do banco escondidas no fim da tela |
| 7 | Espelho (`Mirror.tsx`) | Comprovantes pessoais e "Pedir ajuste deste dia" misturados com a consulta do espelho de outra pessoa |
| 8 | Fechamento (`Admin.tsx:679`) | Configuração de foto na batida está dentro de Fechamento |
| 9 | Pessoas (`Admin.tsx:317`) | Depois de cadastrar não dá para mudar gestor nem data de admissão; o cadastro e a edição são formulários diferentes |
| 10 | Pessoas (`Admin.tsx:234`) | O campo "Gestor" lista qualquer administrador/RH, não quem de fato gere equipe |
| 11 | Empresa | Não existe tela para editar nome, local de trabalho e fuso da empresa |
| 12 | Backend (`deps.py`, routers) | Permissões por listas de perfis repetidas; o gestor é reconhecido só quando é o perfil mais alto |
| 13 | Backend | "Registra ponto" não é verificado ao pedir ajuste, pedir ausência, consultar banco de horas próprio, comprovantes e `/punches/next` |
| 14 | Aprovação | Quem aprova o ajuste do único administrador, se ele também bate ponto? Hoje ninguém (autoaprovação é bloqueada) |
| 15 | Textos | Mensagens citam "gestor" e "RH" mesmo quando a empresa não tem essas funções |
| 16 | Login | Só e-mail e senha; não há "esqueci minha senha"; senha temporária entregue à mão |
| 17 | Sessão | Tokens guardados no `localStorage` (um script malicioso na página os leria) |
| 18 | SaaS | E-mail único no sistema inteiro: a mesma pessoa não pode estar em duas empresas (contador, filiais com outro CNPJ) |

## 2. Modelo proposto

### 2.1 Dois eixos independentes na pessoa

- **Registra ponto** (sim/não): a pessoa está sob controle de jornada. Liga a área **Meu ponto**.
- **Permissões de gestão** (nenhuma, uma ou várias):
  - **Administração**: perfil mestre. Tudo o que RH e Gestão fazem, mais empresa e configurações, Centrais, permissões das
    pessoas, exclusões e auditoria.
  - **RH / Departamento Pessoal**: cadastrar e editar pessoas (sem mexer em permissões), jornadas, ausências de qualquer tipo
    para qualquer pessoa, lançamentos no banco de horas, aprovar ajustes e ausências de todos, fechar e reabrir mês,
    relatórios da empresa, AFD/AEJ, fotos, crachás e PIN.
  - **Gestão de equipe**: painel da equipe, espelho da equipe, aprovar ajustes e ausências (atestado/abono) da equipe,
    relatórios da equipe. "Equipe" = quem tem esta pessoa como gestor.
- **Auditor** (só leitura para a fiscalização): sai da tela. Na prática a fiscalização recebe os arquivos AFD/AEJ; o perfil
  continua no backend caso seja preciso no futuro.

### 2.2 Uma única regra de permissões

- Backend: um módulo `permissions.py` com a matriz **função → ações** (ex.: `approve_adjustment`, `manage_people`,
  `close_month`, `view_team_mirror`, `punch`), e o alcance (própria pessoa, equipe ou empresa). Todas as rotas passam a
  perguntar `can(actor, "acao", alvo)` em vez de comparar perfis. O campo `role` deixa de decidir permissões.
- `GET /auth/me` devolve a lista de ações permitidas; o frontend só pergunta `can("...")`. Some a lista de perfis copiada nas telas.
- Testes de matriz: para cada uma das 5 personas abaixo, cada rota é chamada e o resultado esperado (permitido/negado) é conferido.

### 2.3 Navegação em duas áreas

| Área | Quem vê | Telas |
|------|---------|-------|
| **Meu ponto** | quem registra ponto | Bater ponto · Meus registros (espelho + comprovantes) · Minhas solicitações (ajustes e ausências juntos) · Meu banco de horas |
| **Gestão** | quem tem alguma permissão | Painel (situação de hoje) · Aprovações (ajustes e ausências pendentes numa caixa só) · Espelhos (escolher a pessoa) · Banco de horas da equipe (saldos e lançamentos) · Relatórios · Cadastros (Pessoas, Jornadas, Centrais) · Fechamento · Fiscalização (AFD/AEJ e integridade) · Configurações · Auditoria |

- Quem só gere (ex.: a administradora): só a área Gestão; a tela inicial é o Painel.
- Quem só bate ponto: só Meu ponto, como hoje.
- Quem bate ponto e gere: as duas áreas, com um seletor simples no topo ("Meu ponto | Gestão"); no celular, as abas mudam conforme a área.
- Cada item de Gestão aparece só se a pessoa tem a permissão correspondente (ex.: Gestor de equipe não vê Configurações).
- **Minha conta**: nome, forma de entrar (Google/Apple vinculados), senha (só se usa senha), 2FA (só para quem gere e entra
  com senha) e "Central do Ponto: meu código, crachá e PIN" (só se registra ponto).

### 2.4 Cadastro da pessoa: um formulário só, para criar e editar

Três blocos: **Dados** (nome, CPF, e-mail de acesso, cargo) · **Vínculo e jornada** (registra ponto, admissão, jornada,
gestor, onde bate ponto, banco de horas) · **Acesso** (pode entrar no app, permissões de gestão). O bloco de jornada só
aparece se "Registra ponto" estiver marcado. O campo "Gestor" lista só quem tem Gestão de equipe; vazio = as aprovações vão
para o RH/Administração.

### 2.5 Configurações num lugar só

Empresa (nome, local de trabalho, fuso; CNPJ só leitura) · Banco de horas (limite, prazo) · Foto na batida · Central (PIN
obrigatório, raio padrão) · Login (métodos permitidos, 2FA obrigatório para quem gere).

### 2.6 Quem aprova o quê (sem buraco)

- Ajuste/ausência de quem tem gestor: o gestor aprova; RH e Administração também podem.
- Sem gestor: RH ou Administração.
- Pedido de quem é a única pessoa com permissão de aprovar: **decisão pendente** (ver seção 5).

## 3. Login com Google e Apple

### 3.1 Como funciona

1. A Administração cadastra a pessoa com o e-mail dela (Gmail, Workspace ou iCloud). **Não há cadastro aberto**: só entra quem a empresa cadastrou.
2. Na tela de login: **Entrar com Google** / **Entrar com Apple** (e, se a empresa permitir, e-mail e senha).
3. O navegador recebe do Google/Apple um token assinado; o backend confere a assinatura, o destinatário (nosso Client ID) e
   se o e-mail é verificado, procura a pessoa por esse e-mail e grava o identificador da conta Google/Apple (`sub`) para as
   próximas vezes. A partir daí, o login vale mesmo se a pessoa trocar o e-mail na conta Google.
4. Sem senha temporária, sem "esqueci minha senha": quem perder o acesso recupera pela conta Google/Apple.

### 3.2 Google (recomendado começar por ele)

- Google Identity Services (botão oficial), modo redirecionamento, que funciona bem no app instalado (PWA) inclusive no iPhone.
- Você precisa criar no Google Cloud Console: um projeto, a **tela de consentimento OAuth** (nome do app, logo, e-mail de
  suporte, **link da política de privacidade e dos termos de uso**, que precisam estar publicados) e um **Client ID do tipo
  Web** com a origem `https://ponto.wasadocs.com.br`. Só pedimos `openid email profile`, que não exige verificação demorada do Google.
- Opcional: restringir ao domínio da empresa (Google Workspace).

### 3.3 Apple

- Exige o **Apple Developer Program (US$ 99/ano)**, um *Services ID*, a verificação do domínio (arquivo em
  `/.well-known/apple-developer-domain-association.txt`) e uma chave `.p8` para assinar o *client secret*.
- A Apple deixa a pessoa **esconder o e-mail** (envia um endereço `@privaterelay.appleid.com`). Esse endereço não bate com
  o cadastro, então o vínculo com Apple precisa ser feito **de dentro da conta** ("Vincular Apple" em Minha conta, depois de
  entrar uma vez com Google ou senha) ou por um link de convite.
- O botão "Entrar com Google" também funciona no iPhone; a Apple pode ficar para uma segunda etapa.

### 3.4 Junto com o login

- Sessão: o token de renovação passa para um cookie `HttpOnly` (fora do alcance de scripts); o de acesso fica só em memória.
- 2FA: para quem entra com Google/Apple, vale a verificação da própria conta; o 2FA do app continua para quem usa senha.
- Quem só bate ponto na Central e não usa o app não precisa de login (opção "pode entrar no app").

## 4. Fases

| Fase | Conteúdo | Tamanho |
|------|----------|---------|
| 0 | Decisões da seção 5 | — |
| 1 | `permissions.py` + matriz de testes por persona; todas as rotas migradas; `me` devolve permissões; verificação de "Registra ponto" em todas as rotas pessoais | Grande |
| 2 | Navegação em duas áreas; separar as telas pessoais das de gestão (Ajustes, Ausências, Banco, Espelho); caixa única de Aprovações; Minha conta condicional; textos neutros | Grande |
| 3 | Cadastro único da pessoa (criar/editar tudo); tela de Configurações; remover o Auditor da tela | Médio |
| 4 | Login com Google (backend + tela + vínculo em Minha conta); sessão em cookie HttpOnly; política de privacidade e termos publicados | Médio |
| 5 | Login com Apple (depende da conta de desenvolvedor) | Pequeno/médio |
| 6 | Ensaio completo por persona na VM (roteiro docs/ensaio-fase-b.md atualizado): só colaborador no app; só colaborador na Central; gestor que bate ponto; RH que bate ponto; administradora que só gere | Médio |
| 7 | Entrada em produção: banco **novo** (sem os dados de ensaio, em vez de limpar), cadastro real, backup testado, pendências legais (INPI, certificado ICP-Brasil, validação jurídica, LGPD) | — |

Cada fase termina com testes automatizados verdes, verificação no navegador nas personas afetadas e atualização na VM.

## 5. Decisões necessárias

1. **RH e Gestão de equipe separados** como descrito em 2.1 (Administração inclui tudo)? Recomendado: sim.
2. **Autoaprovação**: se quem pede o ajuste é a única pessoa que poderia aprovar, (a) permitir com justificativa obrigatória
   e registro destacado na auditoria, ou (b) exigir que sempre exista uma segunda pessoa com permissão de aprovar. Recomendado: (a) só para Administração, com aviso.
3. **Login por senha**: manter como alternativa (para quem não tem Google/Apple) ou só Google/Apple? Recomendado: manter, configurável por empresa.
4. **Apple**: há conta no Apple Developer Program? Se não, começamos só com Google.
5. **Auditor**: tirar da tela? Recomendado: sim.
6. **Quem bate ponto só na Central precisa entrar no app?** (para ver espelho e comprovantes) Recomendado: opcional por pessoa.
7. **Mesma pessoa em duas empresas** (item 18): resolver agora ou depois da produção? Recomendado: depois, se surgir o caso.
