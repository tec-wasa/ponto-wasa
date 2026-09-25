# Central do Ponto — plano de desenvolvimento

Status: **decisões tomadas; fases 1 (servidor), 2 (Gestão), 4 (colaborador) e 3 (tela `/central`) concluídas**. Mockups navegáveis: `design/central-mockup.html` (tablet na horizontal) e `design/central-mockup-vertical.html` (tablet na vertical, tudo em uma coluna, ações empilhadas).

## 1. As três interfaces, em sintonia

| | Administrador (Gestão) | Colaborador | **Central do Ponto** (nova) |
| --- | --- | --- | --- |
| Quem usa | RH, administrador, auditor, gestor | Cada pessoa, no próprio celular/computador | Todas as pessoas, num **aparelho único** compartilhado (tablet fixo) |
| Aparelho | Qualquer | Pessoal (PWA instalável) | Cadastrado e vinculado a um posto; pode ser revogado |
| Autenticação | E-mail + senha (+2FA) | E-mail + senha (+2FA) | O **aparelho** se autentica (token de pareamento); a **pessoa** se identifica a cada batida (QR ou código/CPF + PIN) |
| Sessão | Longa (8 h) | Longa | **Nenhuma** sessão de pessoa: um "ticket" de 60 s, uso único |
| O que vê | Tudo do escopo | Só os próprios dados | **Só o primeiro nome** e a própria linha do tempo do dia |
| O que faz | Cadastros, jornadas, fechamento, relatórios, fiscalização, aprovações | Registrar ponto, Espelho, ajustes, ausências, banco de horas | Registrar ponto (+ foto + local). Mais nada |
| Origem gravada na marcação | — | `01` app / `02` navegador | `04` Central (+ identificação do aparelho) |

Princípio: as três usam **o mesmo motor** (NSR, hash, ordem das batidas, encerramento à meia-noite, 4 batidas por jornada, foto, auditoria). A central é só um **coletor novo** com identificação própria; nenhuma regra de negócio é duplicada.

## 2. A Central: fluxo e regras

Fluxo (ver mockup): **Espera → Identificar → Confirmar (PIN) → Foto → Registrado → volta à Espera**.

1. **Espera:** relógio grande (sincronizado com o servidor), data, duas ações: "Aproxime o QR Code" e "Digitar código ou CPF". Volta sozinha a esta tela após 8 s do registro e 30 s sem toque.
2. **Identificar**
   - **QR do crachá** (impresso, fixo): contém o código da pessoa assinado (HMAC) e uma versão do crachá (revogável).
   - **QR do aplicativo** (Minha conta → "Meu crachá"): rotativo (janela de 30 s, como TOTP), não vale como foto de tela.
   - **Código interno** (4–8 dígitos, gerado pelo sistema, não derivado do CPF) ou **CPF** (11 dígitos), digitado num teclado numérico grande.
3. **Confirmar:** "Olá, Ana" + **PIN de 4 dígitos** (definido pela pessoa; obrigatório com código/CPF/crachá impresso; opcional com o QR rotativo, conforme política). Erro genérico ("código ou PIN incorreto"), nunca dizendo qual dos dois falhou. 5 erros bloqueiam o código por 5 min (e o aparelho fica mais lento para tentativas em série).
4. **Mostrar a próxima batida** ("2ª · Intervalo") e a linha do tempo do dia da própria pessoa.
5. **Foto:** contagem de 3 s, foto na câmera frontal do aparelho. **Opcional por natureza**: recusa, câmera com defeito ou falta de consentimento = registra sem foto, com o aviso. Na primeira vez, a central pede o consentimento LGPD (mesmo texto do aplicativo).
6. **Local:** o aparelho tem um **posto fixo** (coordenadas + raio) cadastrado pelo administrador. A central lê o GPS na hora e o servidor guarda a distância ao posto. Fora do raio ou sem GPS **não bloqueia**: marca "fora do posto" para o RH. (O que se registra é a posição do aparelho, não a da pessoa.)
7. **Registrar:** o servidor usa a hora dele, escolhe o tipo pela ordem, aplica "jornada encerrada" e devolve NSR, hash curto e a nova linha do tempo. O comprovante completo fica no aplicativo da pessoa (Registros).

Erros previstos na tela: código/PIN incorretos, PIN bloqueado, jornada encerrada, central sem conexão, relógio fora de sincronismo, aparelho revogado.

**Fora da v1:** central sem internet (identificar sem servidor exige guardar dados de todos no aparelho: risco alto), leitor USB/NFC, reconhecimento facial (não faremos: dado biométrico sensível).

## 3. Decisões de segurança e conformidade

- **CPF sozinho não identifica bem** (é dado quase público). Por isso PIN obrigatório com CPF/código; a foto ajuda a conferir depois, não impede.
- **Fraude por "bater pelo colega":** mitigada por PIN pessoal, QR rotativo, foto na batida, relatório de divergências (mesma pessoa em dois lugares, fora do posto, sem foto). Não é eliminada; a foto é indício, não prova.
- **Tela pública:** nunca lista pessoas; nunca mostra CPF completo (mascara ao digitar depois de 3 s); mostra só o primeiro nome.
- **Aparelho:** pareamento com código de uso único (15 min) emitido pelo administrador; token do aparelho guardado com hash no servidor; revogação imediata; `last_seen` para detectar aparelho parado. Recomenda-se modo quiosque do sistema (Android "fixar tela" / iOS "Acesso Guiado").
- **Coletor no AFD:** a marcação usa o código de coletor `04` (dispositivo). **Hipótese H8:** confirmar com a homologação que `04` cabe para "central em tablet compartilhado" e como isso aparece no Atestado Técnico.
- **Consentimento:** a foto exige consentimento por pessoa (já existe). A central coleta o consentimento na primeira batida, e a pessoa pode revogar em Minha conta.
- **Auditoria:** identificação, falha de PIN, bloqueio, pareamento, revogação e cada batida da central (`kiosk_*`), sem gravar PIN nem código completo.

## 4. Modelo de dados e API

Migração `0008` (mesmas convenções: append-only só onde já é; novas tabelas mutáveis):

- `kiosks` — `id, company_id, name, token_hash, pairing_code_hash, pairing_expires_at, latitude, longitude, radius_m, active, last_seen_at, created_by, revoked_at`.
- `users` (+colunas) — `employee_code` (único por empresa), `pin_hash` (argon2), `pin_fails`, `pin_locked_until`, `pin_must_change`, `badge_version`, `badge_secret` (cifrado, para o QR rotativo).
- `punches` (+colunas) — `kiosk_id` (FK, nulo), `distance_m` (nulo); `collector="04"`; `device_id="kiosk:<id>"`. **O hash da marcação não muda de fórmula** (H1 já cobre o coletor).
- `punch_photos` — sem mudança (reaproveitada).

Endpoints (novo roteador `kiosk`, autenticado por `X-Kiosk-Token`):

| Rota | Função |
| --- | --- |
| `POST /kiosk/pair` | Troca o código de pareamento pelo token do aparelho |
| `GET /kiosk/state` | Empresa, fuso, hora do servidor, política, posto do aparelho |
| `POST /kiosk/identify` | `{method: qr|code|cpf, value, pin}` → ticket (60 s, uso único) + primeiro nome + próxima batida + linha do tempo do dia |
| `POST /kiosk/consent-photo` | `{ticket}` |
| `POST /kiosk/punch` | `{ticket, photo?, lat?, lon?, client_key}` → NSR, hash curto, nova linha do tempo |

Administração: `POST/GET/DELETE /admin/kiosks` (+ novo código de pareamento), `POST /users/{id}/pin-reset`, `POST /users/{id}/badge` (regenerar), `GET /users/{id}/badge.pdf` e `GET /badges.pdf` (lote). Colaborador: `POST /auth/pin`, `GET /auth/badge-qr` (payload rotativo).

Reaproveitados sem alteração: `register_punch`, `next_kind`, `day_closed`, fotos (`photos.save`, S3), NSR/ARP, limites de tentativas (generalizar `audit_log` de login), Espelho/AEJ/AFD.

## 5. O que muda nas outras interfaces

**Administrador (Gestão)**
- Nova aba **Centrais**: cadastrar aparelho, mostrar o código de pareamento (uma vez), definir posto (lat/lon/raio, com "usar minha localização atual"), ver `last_seen` e batidas do dia, revogar.
- **Pessoas:** mostrar/gerar código interno; redefinir PIN; regenerar/imprimir crachá QR (individual e lote em PDF); desbloquear PIN; política por pessoa "bate ponto em: central / aplicativo / ambos".
- **Empresa/política:** exigir PIN (padrão sim); solicitar foto na central (padrão sim, sempre com "sem foto"); raio padrão; bloquear registro pelo aplicativo para quem usa só a central.
- **Importação CSV:** coluna `codigo` (opcional; gerado se vazio).
- **Relatórios:** filtro por origem; novo relatório **Divergências da central** (fora do posto, sem foto, falhas de PIN, aparelho parado).
- **Auditoria:** nomes legíveis para os eventos `kiosk_*`. **Fiscalização:** documentar o coletor `04`.

**Colaborador**
- **Minha conta:** definir/alterar PIN; ver o código interno; **Meu crachá** (QR rotativo em tela cheia, brilho alto).
- **Registros/Espelho:** mostrar a origem de cada batida ("Central CT-01" / "Aplicativo") e o comprovante como hoje.
- **Tela de ponto:** se a política for "só central", o botão fica desativado com a explicação; o registro sem internet continua igual para quem pode bater pelo app.
- **Ajustes:** sem mudança (o pedido "esqueci de bater" continua valendo para batidas de qualquer origem).

**Comum**
- Rótulos da origem no Espelho em PDF e no AEJ (campo de coletor já existe); `PUNCH collector` "04" na lista permitida (já prevista); `/kiosk/*` fora da autenticação de usuário e com limite de tentativas próprio; Service Worker e manifesto próprios da central (`/central`), para instalar como app separado ("Ponto Central") sem misturar cache e sessão com o aplicativo pessoal.

## 6. Plano em fases

| Fase | Entrega | Testes / critério de pronto |
| --- | --- | --- |
| **0. Decisões** | Respostas às perguntas da seção 7; validar H8 e o texto de consentimento com o jurídico | Decisões registradas no README |
| **1. Base no servidor** | Migração 0008; códigos internos; PIN (argon2) com bloqueio; QR do crachá assinado e QR rotativo; pareamento e autenticação do aparelho; `identify` + `punch` + `consent-photo` | Testes: ticket de uso único e expirado; PIN errado/bloqueio; **sem enumeração** (mesma resposta para código inexistente e PIN errado); revogação do aparelho; isolamento entre empresas; jornada encerrada; foto opcional; distância ao posto; hash/NSR íntegros; PostgreSQL (papéis e grants) |
| **2. Gestão** | Aba Centrais; código/PIN/crachá nas Pessoas; PDF de crachás; políticas; CSV | Testes de API e verificação no navegador; PDF conferido visualmente |
| **3. Interface da Central** | Rota `/central` (entrada própria, PWA própria): estados do mockup, teclado, leitura de QR pela câmera, foto, GPS, contagens e retorno automático, modo tela cheia e "manter tela ligada" | Testes de estados; verificação no navegador (câmera e GPS simulados); **teste em tablet real**; acessibilidade (alvos ≥ 64 px, contraste, leitor de tela) |
| **4. Colaborador** | PIN em Minha conta, Meu crachá (QR rotativo), origem nos Registros, política "só central" | Testes e verificação no navegador |
| **5. Relatórios, fiscalização e piloto** | Origem nos relatórios/Espelho/AEJ, relatório de divergências, auditoria legível, documentação de instalação do tablet | Piloto de 1–2 semanas num posto; ajustes |
| **6. Depois** | Central sem internet (com lista local protegida), leitor USB/NFC, vários postos por central, notificação ao colaborador | Novo plano |

Ordem de dependência: 1 → (2 e 3 em paralelo) → 4 → 5. Cada fase termina com suíte verde, verificação no navegador e README atualizado.

## 7. Decisões tomadas

1. **PIN:** a exigência é **configurável pelo administrador** (`kiosk_pin_required`, padrão **desligado**: não é obrigatório). Quando ligada, vale para código, CPF e QR do crachá impresso; o **QR rotativo do aplicativo dispensa o PIN** (o celular já é a prova). Sem PIN exigido, código ou CPF sozinho identifica: o README e a tela de Gestão avisam que o código deve ser tratado como senha.
2. **Foto:** **obrigatória** na Central. Sem foto (ou sem consentimento) não há batida por ali; quem não quiser usa o aplicativo. O aplicativo pessoal continua com foto opcional.
3. **Aplicativo pessoal:** continua liberado para todos (a política "só central" fica para depois).
4. **QR rotativo do aplicativo:** **incluído** na v1.
5. **Central sem internet:** fora da v1.
6. **Piloto:** de **1 a 5 aparelhos** por empresa (limite `PONTO_KIOSK_MAX_PER_COMPANY=5`), raio de tolerância **100 m** (configurável por aparelho).
7. **Texto de consentimento** (mesmo tom do aplicativo; enviado pela API em `GET /kiosk/state` e mostrado na primeira batida de cada pessoa):

   > Nesta central, a foto é obrigatória em cada batida. Ela serve só para o RH conferir que foi você, fica guardada com criptografia, só o RH e o administrador a veem e ela é apagada quando o mês é fechado. Você pode recusar: nesse caso, registre o ponto pelo aplicativo.

**Ajuste no fluxo do mockup por privacidade:** quando o PIN é exigido, a tela pede o PIN **antes** de mostrar o nome ("Olá, Ana" só aparece depois de identificar). O mockup atual mostra o nome antes do PIN; será corrigido na fase 3.

## 7.1 Status

| Fase | Situação |
| --- | --- |
| 0. Decisões | Feita (seção acima); pendente só a validação jurídica do coletor `04` (H8) |
| 1. Base no servidor | **Concluída** (ver README, "Central do Ponto: servidor") |
| 3. Interface da Central | **Concluída** (falta o teste em tablet real; ver README, "Central do Ponto: tela /central") |
| 2. Gestão | **Concluída** (aba Centrais, código/PIN/crachás nas Pessoas, PDF de crachás; falta política "só central", coluna `codigo` no CSV e relatório de divergências, previstos na fase 5) |
| 4. Colaborador | **Concluída** (PIN, Meu crachá, origem nos comprovantes, política "só Central") |
| 5. Relatórios e importação | **Concluída** (batidas por origem, divergências, `codigo` no CSV; falta origem no Espelho PDF e o piloto) |
| 6. Depois | **Parcial**: leitor USB/Bluetooth e Central sem internet (opção C) feitos; NFC, vários postos e notificação ao colaborador ficam para depois |

## 8. Riscos

- **Fraude entre colegas** (PIN emprestado): reduzida, não zerada; depende de relatórios e da foto.
- **Fila na hora do pico:** tempo por batida deve ficar em ~10 s (QR + PIN + foto). Se o RH quiser mais velocidade, a foto pode ser dispensada por política.
- **Câmera/GPS do tablet:** dependem de HTTPS e permissões; incluir roteiro de instalação e verificação do aparelho na fase 5.
- **Fotos em volume:** todas as batidas da central podem gerar foto (~50 KB); retenção continua "até o fechamento do mês"; com o bucket S3 o custo é baixo.
- **Aparelho parado ou roubado:** `last_seen`, alerta no painel e revogação imediata.

## 8. Fase 6: leitor USB/Bluetooth e Central sem internet

**Leitor em modo teclado (feito).** Na espera e na tela do QR, a Central escuta o teclado: uma sequência rápida de teclas (até 60 ms entre elas) terminada em Enter, com o formato de um QR do Ponto (`PB1…` ou `PR1…`), identifica a pessoa como se a câmera tivesse lido. Digitação humana nunca completa uma leitura; códigos de outros formatos mostram "Código não reconhecido". Serve para leitores USB e Bluetooth de fábrica (modo HID). **NFC** ficou de fora: exige leitor e cartão próprios e um novo tipo de identificador. Verificado só por testes unitários do buffer; falta testar com um leitor real e a integração na tela.

**Central sem internet: opção C escolhida e implementada.** Só o **QR do crachá impresso** (`PB1…`) vale sem internet; o QR rotativo do aplicativo, o código e o CPF exigem conexão. O tablet **não guarda dados de pessoas**: ele guarda, por batida, o QR lido (opaco para ele), a foto, a hora (relógio do aparelho corrigido pelo desvio medido na última conexão) e a posição. Ao voltar a internet (evento `online` ou a cada 20 s), envia a fila em ordem para `POST /kiosk/offline-punch`, e **é o servidor que confere tudo**:

- assinatura e versão do crachá (crachá regenerado depois da leitura = recusada), pessoa ativa, mesma empresa;
- hora não futura e dentro de `OFFLINE_MAX_HOURS` (mesma regra H7 do aplicativo);
- consentimento da foto já dado (senão recusa; a pessoa consente no aplicativo ou na Central com internet);
- sequência do dia (o tipo da batida é decidido no servidor, pela ordem; jornada encerrada = recusada);
- idempotência por `client_key` (reenvio não duplica batida nem foto).

Recusas nunca gravam batida: ficam na auditoria (`kiosk_offline_rejected`, com o motivo) e no relatório **Divergências da Central** ("Batida sem internet recusada"); a pessoa corrige por Ajuste. A batida aceita sai com `offline=true`, coletor `04` e origem "Central".

Limites e efeitos: **desligada quando a empresa exige PIN** (o PIN não pode ser conferido offline); fila de até 40 batidas ou ~3,5 MB de fotos (cheia = a Central avisa e não aceita, nunca perde em silêncio); a tela não mostra nome, tipo nem NSR ("Batida guardada", sem confirmar quem), então quem bate não sabe na hora se será aceita; o crachá impresso é o único fator (a foto e o relatório de divergências são o controle). Cuidado: revogação do crachá só vale no envio; um crachá roubado pode gerar batidas guardadas até a conexão voltar (a foto mostra quem foi). NFC continua fora.
