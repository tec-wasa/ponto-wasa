# Benchmark: portal Sólides Ponto (Tangerino)

Análise feita em 27/11/2026 no portal web do Sólides Ponto (app.tangerino.com.br), com a conta da empresa.
Só navegação e leitura: nenhum registro foi salvo, aprovado ou lançado. Os nomes de colaboradores vistos no
portal não foram copiados para cá.

**Como ler:** cada item diz o que o portal faz e se o nosso app já tem isso.
- ✅ já temos
- 🟡 temos uma parte
- ❌ não temos

A prioridade sugerida (P1 > P2 > P3) pesa o impacto no fechamento do mês e o risco trabalhista.

---

## 1. Mapa do portal (menu completo)

| Área | Telas |
|---|---|
| Empregador | Dados cadastrais · Integrações · Auditoria · PRO |
| Cadastros gerais | Administradores · Colaboradores · **Ações em lote** · Gestores · **Meus contadores** · Local de trabalho/setor · Cargos · Função · Escalas · Calendário de feriados · Filiais |
| Ponto › Colaborador | Apropriação de horas · Local de interesse · **Enviar mensagens** · **Cobertura de faltas** · **Ass. eletrônica de folha de ponto** |
| Ponto › Controle de ponto | Bater ponto · **Gestão de banco de horas** · Ajuste de banco de horas · Atestados e afastamentos · Fechamento de ponto · **Gestão de ajuste em lote** · Arquivos fiscais · **Comparativo de marcações externas** |
| Ponto › Relatórios (14) | **Eventos de folha de pagamento** · Folha de ponto · Banco de horas / Hora extra · Sintético · Faltas / Atrasos / Absenteísmo · Escala de trabalho · Coleta de pontos originais · Motivos de ajustes · Informação adicional de ponto · Visita a local de interesse · Ponto com endereço · Benefícios · Colaboradores com foto · Horas por local de trabalho · Falhas de reconhecimento facial |
| Ponto › Configurações | Configurações gerais · **Regras de ponto** · Justificativas de atraso · **Motivos de ajuste** · Controle de dispositivos · Relógio de ponto |
| Fora do escopo de ponto | Gestão de atividades · WhatsApp · Férias (módulo pago) · Intranet (comunicados, enquetes, humorômetro) · Gestão externa (ordens de serviço, questionários, monitoramento de rota, reembolso, distância percorrida) · Saúde ocupacional (NR-1) |
| Atalhos no topo | Pontos pendentes · Ajuste de pontos pendentes · Inconsistências · Atestados e afastamentos · Ponto em atraso |

---

## 2. Funcionalidades interessantes, por tema

### 2.1 Regras de cálculo ("Regras de Ponto")

No portal, a regra de cálculo é um cadastro à parte, com nome, que se vincula às pessoas. Há aviso para
**duplicar a regra em vez de alterá-la**, porque alterar recalcula o passado.

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| Regra com nome, separada da jornada, vinculada a grupos de pessoas; botão **Duplicar regra** | Sim | ❌ banco de horas e tolerância ficam na empresa e na jornada | P2 |
| Tipo de controle: **Banco de horas** ou **Hora extra** (paga) | Sim | 🟡 banco liga/desliga por pessoa; sem modo "hora extra paga" com faixas | P1 |
| **Faixas de hora extra** (1ª fase, 2ª fase, excedente) separadas para dias úteis, sábados, domingos e feriados, diurnas e noturnas, com **percentuais por tipo** (50 %, 100 %, …) | Sim | ✅ implementado em 27/11/2026: duas faixas por tipo de dia (Empresa › Configurações), relatório "Horas extras" e linha no espelho. Sem faixa noturna separada (minutos noturnos à parte) | — |
| Hora noturna: configurável entre **hora ficta** (7 h = 8 h) e padrão; início e fim ajustáveis (19h–08h); **hora noturna estendida** (Súmula 60) | Sim | 🟡 hora reduzida fixa das 22h às 5h, sem prorrogação | P2 |
| Controle de atrasos: horário **flexível** ou **rígido** + tolerância | Sim | 🟡 temos a tolerância | P3 |
| **Dia de fechamento da folha** (ex.: período de 21 a 20) | Sim | ❌ o mês é sempre o calendário | P1 |
| **Código externo** da regra e da escala (para a folha) | Sim | ❌ | P2 (vem junto com 2.6) |
| Banco: vencimento **a partir da competência** ou em **intervalos fixos** (mensal até anual) | Sim | 🟡 prazo único em meses | P2 |
| Banco: **acréscimo %** ao creditar em dia útil, sábado, domingo e feriado | Sim | ❌ | P2 |
| Banco: **limite diário, semanal e mensal** (o excedente vira hora extra) | Sim | 🟡 só o teto do saldo | P2 |
| Banco: levar sábados, domingos, feriados ou noturno para **hora extra** em vez do banco | Sim | ❌ | P2 |
| Banco: **descontar faltas automaticamente** e **abater sem acréscimo no mesmo mês** | Sim | 🟡 a falta já gera débito; a compensação no mês não é tratada à parte | P3 |

### 2.2 Escalas (jornadas)

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| Horário **por dia da semana** (quantidade de períodos por dia) | Sim | ❌ a jornada tem os mesmos horários em todos os dias marcados | P1 |
| **Escala cíclica** (12x36, 6x1, 5x2 alternado) | Sim | ❌ | P1 se houver plantão; senão P3 |
| **Escala livre** (sem horário fixo) | Sim | 🟡 dá para simular com tolerância | P3 |
| **Intervalo pré-assinalado** (Art. 74 §2º: a pessoa não bate o almoço) | Sim | ❌ | P2 |
| **Ignorar feriado** em uma escala | Sim | ❌ o feriado vale para todos | P3 |
| Escala **"Não registra ponto"** | Sim | ✅ (`tracks_time`) | — |
| **Abonar horário** fixo de um dia da escala | Sim | ❌ | P3 |
| Escala padrão para quem é cadastrado sem escala | Sim | ❌ | P3 |
| **Relatório da escala de trabalho** | Sim | ❌ | P3 |

### 2.3 Tratamento diário ("Apropriação de horas")

Visão dia a dia de cada pessoa: pares entrada/saída, total, endereço da entrada e da saída, anexos, selo
"Editado manualmente", trabalhadas/intervalos/previsto/saldo do dia e cadeado "Ponto fechado em…".
Menu **Ações do dia**:

| Ação do dia | Nosso app | Prioridade |
|---|---|---|
| Coleta de pontos originais (o que o aparelho gravou, sem tratamento) | ✅ o ARP é imutável; mostrar "original × tratado" lado a lado pode melhorar | P3 |
| **Histórico de alterações do dia** | 🟡 está na auditoria, mas não aparece no próprio dia | P2 |
| Lançar ponto em atraso (incluir marcação) | ✅ inclusão no tratamento | — |
| **Preenchimento automático** (completa o dia com o horário da escala) | ❌ | P2 |
| Lançar motivo de ajuste (abono parcial ou total) | ✅ abono | — |
| Lançar atestados e afastamentos | ✅ | — |
| **Lançar sobreaviso** | ❌ | P3 |
| Consultar escala do dia | 🟡 | P3 |
| Reprocessar ponto (recalcular o dia) | não se aplica: nosso cálculo é sempre na hora | — |
| Excluir marcação (com justificativa obrigatória, configurável) | ✅ desconsideração com motivo | — |
| **Anexos** na marcação/ajuste | 🟡 conferir se a solicitação aceita anexo | P2 |

### 2.4 Inconsistências (tela própria + configuração)

Tela que lista inconsistências por período, com filtros (pessoa, gestor, cargo, setor, tipo), botões
**Reanalisar**, **Marcar como resolvido** e **Abrir apropriação**, e exportação para Excel e PDF.
Na configuração, cada tipo pode ser ligado ou desligado e ter um limite:

- Falta · Ponto em aberto · Falta de registro do almoço · **Intervalo inferior ao previsto**
- Hora extra acima de X h/dia e de Y h/semana · hora extra noturna · hora extra abaixo de um mínimo
- **Jornada acima do limite máximo diário** · **Mais de X h sem intervalo**
- **Interjornada menor que 11 h** (Art. 66) · **Mais de X dias sem folga** (DSR, Art. 67)
- **Ponto britânico** (horários idênticos todos os dias) · saldo negativo acima de X · limite mensal do banco excedido
- **E-mail diário com o resumo das inconsistências** para gestores e administradores

**Nosso app:** ✅ **implementado** em Gestão > Inconsistências (27/11/2026). Tem falta, saída ausente, intervalo
(art. 71), mais de 6 h sem intervalo, mais de 2 h extras (art. 59), interjornada (art. 66), 7º dia (art. 67) e
ponto britânico. Também dá para marcar como resolvida (com observação) e reabrir, filtrar por pessoa e tipo,
baixar o CSV e abrir o dia no Tratamento. **Ficou de fora:** limites configuráveis por empresa (hoje são os
da CLT) e o e-mail diário com o resumo (o app ainda não envia e-mail).

### 2.5 Pontos pendentes (batida sob suspeita)

O portal marca a batida como **pendente de aprovação** quando: data/hora do aparelho manual, fuso manual,
GPS desligado, **suspeita de Fake GPS**, falha no reconhecimento facial, **fora do local de interesse**,
batida em **período de férias** ou ponto em atraso. A fila tem **aprovação em lote** e exporta para Excel.
As notificações têm nível (Info, Alerta, Crítico) por tipo.

**Nosso app:** 🟡 marcamos `outside_radius` e a distância, e o relatório "Divergências da Central" lista os
casos, mas **sem fila de aprovação**. P2. Atenção: na Portaria 671 a marcação não pode ser bloqueada nem
alterada, então "pendente" aqui deve ser **um alerta para o gestor revisar**, nunca uma batida que só passa a
valer depois de aprovada.

### 2.6 Folha de pagamento e contador

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| **Exportar eventos para a folha** com layouts prontos para cerca de 70 sistemas (Domínio, Alterdata, Fortes, Questor, Totvs RM, Sênior, Contmatic, Nasajon, SCI, Folha Sólides, eSocial…) | Sim | ✅ implementado em 27/11/2026 (Gestão › Folha de pagamento): Domínio (TXT de lançamentos, com datas de falta e DSR), Alterdata (movimento de Lançamento por Funcionário) e CSV; código de cada verba e matrícula de cada pessoa. Os outros sistemas ficam com o CSV | — |
| **Configuração de eventos** (código de cada verba: HE 50 %, HE 100 %, adicional noturno, falta, DSR) | Sim | ❌ | P1 (vem junto) |
| **"Meus contadores"** + **"Enviar para a Central do Contador"** | Sim | ❌ | P2: perfil de contador externo com acesso só de leitura e exportação |
| Gestão de banco de horas: **quitação** (zerar o saldo vencido, pagar como hora extra, quitar até um limite ou valor a valor), em lote, por competência | Sim | 🟡 temos ajuste manual de saldo | P2 |
| Ajuste de banco de horas: **saldo inicial em lote** (implantação) | Sim | 🟡 conferir se a importação cobre | P2 |

### 2.7 Fechamento e assinatura

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| **Data de fechamento** que trava alterações anteriores; **fechamento automático a cada 90 dias**; histórico | Sim | ✅ fechamento por mês, com auditoria; 🟡 sem fechamento automático | P3 |
| Fechamento **por pessoa** (aba Colaboradores) | Sim | ❌ só da empresa | P3 |
| **Assinatura eletrônica da folha de ponto pelo colaborador** no aplicativo (foto exigida, solicitação em lote por filtro, situação de cada assinatura e do processamento em lote) | Sim | 🟡 bloco de ciência para assinar no papel; PDF assinado pela empresa (ICP) | **P1**: acaba com o papel no fim do mês |
| Atestados com situação **Em análise / Ciente / Em desacordo** (resposta do colaborador) | Sim | 🟡 temos aprovação; não temos "ciente / em desacordo" do colaborador | P3 |
| Arquivos fiscais: **importar AFD** de relógio físico + histórico de exportações | Sim | ✅ AFD/AEJ exportam; 🟡 importação só por CSV | P3 |
| **Comparativo de marcações externas** (nossas × de outro relógio) | Sim | 🟡 temos a importação | P3 |

### 2.8 Ajustes em massa e cadastros

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| **Ajuste em lote**: um motivo (ex.: ponte de feriado, queda de energia) num período, para várias pessoas, de dia inteiro ou só um trecho de horário; também **exclusão em lote** | Sim | ✅ implementado em 27/11/2026 (Gestão › Ausências: abono ou férias coletivas, conferir antes, cancelar o lote inteiro). O trecho é informado em horas, não por horário de início e fim | — |
| **Ações em lote** por planilha: baixar a planilha filtrada, editar e subir (cadastro, saldo de banco, tempo máximo de jornada) | Sim | 🟡 importação CSV de pessoas (só inclusão) | P2 |
| **Cadastro de motivos de ajuste** com flags: abona? conta falta? entra no absenteísmo? liberado para gestor? para colaborador? ativo? (ABONO, ATESTADO DE ACOMPANHAMENTO, AVISO PRÉVIO, COMPENSAÇÃO, DAY OFF, FALTA JUSTIFICADA ABONADA/NÃO ABONADA…) | Sim | 🟡 os tipos de ausência estão fixos no código | P2 |
| **Justificativas de atraso** cadastráveis (anexo e observação obrigatórios) | Sim | ❌ o motivo é texto livre | P3 |
| Cargos, Função, **Local de trabalho/setor**, **Filiais**, **Centro de custo** (filtros em todos os relatórios) | Sim | 🟡 temos cargo (texto) e gestor | P2: setor e centro de custo para filtrar relatórios |
| **Tipos de vínculo** que batem ponto (CLT, estágio, aprendiz, sócio, prestador…) | Sim | ❌ | P3 |
| **Day off de aniversário** automático | Sim | ❌ | P3 (benefício simpático e simples) |
| **Cobertura de faltas** (substituto vindo da reserva técnica) | Sim | ❌ | fora do nosso perfil |

### 2.9 Registro do ponto, aparelhos e segurança

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| Ponto pelo app: **em qualquer aparelho / só aparelhos autorizados / nunca**; mesma escolha para o navegador; lista de aparelhos autorizados; **colaborador pede autorização do aparelho** | Sim | 🟡 `punch_policy` (app+Central ou só Central); sem lista de aparelhos | P2 |
| **Locais de interesse**: cerca virtual com nome ("Sede", "Cliente X"); "só bater dentro do local"; relatório de visitas | Sim | 🟡 raio só para a Central | P2 |
| Exigir foto no app, no ponto em atraso e na assinatura; **reconhecimento facial** online | Sim | 🟡 foto opcional no app e obrigatória na Central; sem reconhecimento | P3 |
| Detectar **hora manual, fuso manual, GPS desligado, Fake GPS** | Sim | ❌ (num PWA o acesso é limitado; a hora já é a do servidor) | P3 |
| **Lembrete de ponto** (notificação push) | Sim | ❌ | P2 |
| **Enviar mensagens** push para colaboradores | Sim | ❌ | P3 |
| **Aplicativo só de consulta** para algumas pessoas | Sim | 🟡 temos `app_access` | — |
| Colaborador **edita o próprio ponto** até X dias para trás / lança atestado / **limite de ajustes por mês** | Sim | ✅ solicitações; 🟡 sem prazo retroativo nem limite configurável | P2 |
| **2FA (PIN + CPF)** no login do colaborador | Sim | ✅ TOTP e Google | — |
| Permissões de relatório para o colaborador (folha, banco, sintético) | Sim | ✅ espelho e banco no app | — |

### 2.10 Painel e relatórios

| Funcionalidade | Portal | Nosso app | Prioridade |
|---|---|---|---|
| Visão geral: contadores de **pendências do período** (pontos, ajustes, atestados, inconsistências) + horas excedentes, **sem presença**, **férias**, **pontos em aberto**, **top 5 pendências por gestor** | Sim | ✅ painel do mês e "quem está trabalhando"; 🟡 sem os contadores de pendência | P2 |
| **Relatório sintético** (banco, HE, horas totais, sobreaviso) por filtro, em PDF ou Excel | Sim | ✅ fechamento mensal | — |
| **Faltas / atrasos / absenteísmo** (detalhado, sintético e **índice de absenteísmo**) | Sim | 🟡 faltas no fechamento; sem índice | P2 |
| Ponto com endereço · Colaboradores com foto · Horas por local · Motivos de ajuste · Coleta de originais | Sim | 🟡 temos "Batidas por origem" e divergências | P3 |
| Filtros padrão em tudo: colaborador, **filial, setor, gestor, cargo, centro de custo**, situação (ativo/desligado) | Sim | 🟡 gestor e período | P2 |

---

## 3. Recomendação: o que incluir primeiro

**P1: impacto direto no fechamento e no passivo**
1. **Inconsistências da CLT** com lista única e "marcar como resolvido": interjornada de 11 h, intervalo mínimo e mais de 6 h sem intervalo, DSR (mais de 6 dias sem folga), jornada acima do limite e ponto britânico, com e-mail diário opcional.
2. **Ajuste em lote** (abono de um período ou trecho para várias pessoas) e exclusão em lote.
3. **Exportação de eventos para a folha** (Domínio e Alterdata primeiro) com cadastro de códigos de verba.
4. **Hora extra com faixas e percentuais** (50 % e 100 %, dia útil, sábado, domingo e feriado, diurna e noturna) e **dia de corte da folha**.
5. **Assinatura eletrônica do espelho pelo colaborador** no app, solicitada em lote, com situação de cada pessoa.
6. **Jornada com horário por dia da semana** (e, se houver plantão, escala cíclica 12x36).

**P2: maturidade**
Regras de ponto nomeadas e duplicáveis · quitação de banco (pagar ou zerar o vencido) · cadastro de motivos
com flags · fila de batidas suspeitas (só alerta) · locais de interesse para o app · aparelhos autorizados ·
lembrete de ponto · prazo retroativo e limite de solicitações · setor, filial e centro de custo como filtros ·
perfil de contador · índice de absenteísmo · contadores de pendências no painel · histórico de alterações no
próprio dia · preenchimento automático pelo horário da escala.

**P3 / fora do escopo**
Sobreaviso, escala livre, day off de aniversário, tipos de vínculo, fechamento por pessoa, importação de AFD,
mensagens push, reconhecimento facial e detecção de Fake GPS. **Não recomendo**: WhatsApp, Intranet
(enquetes e humorômetro), gestão externa (ordens de serviço, rota, reembolso), cobertura de faltas e saúde
ocupacional, que são produtos à parte e não ajudam o controle de ponto.
