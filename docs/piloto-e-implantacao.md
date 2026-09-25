# Roteiro de piloto e implantação

Objetivo: colocar o Ponto (aplicativo do colaborador, Gestão e Central do Ponto) em uso real com risco controlado, validando o que só um ambiente real mostra. Este roteiro **não substitui a validação jurídica e a homologação** (ver seção 7).

Estado atual do que foi verificado: testes automatizados (backend e front), navegador de desktop/celular emulado e, em PostgreSQL 18 local (sem Docker): `python -m app.dbinit` com as migrações 0001–0009 e o papel restrito, `alembic check` sem divergência, permissões do `ponto_app` conferidas, a suíte inteira (230 testes, incluindo os de PostgreSQL) e um roteiro de fumaça com a aplicação rodando como `ponto_app` (Central, foto, batida sem internet, relatórios, crachás). Com Docker Desktop (Windows): a imagem construiu, a pilha do `deploy/docker-compose.yml` subiu completa (banco, migração, aplicação, Caddy com HTTPS, backup), o roteiro de fumaça passou por HTTPS, o backup em contêiner gerou dumps e a restauração num banco novo passou na conferência de integridade (183 marcações, cadeia íntegra). **Nunca executado:** o workflow do CI no GitHub, domínio público com Let's Encrypt, tablet real, impressão de crachás, provedor S3 real, câmera/GPS reais.

## 1. Fases

| Fase | Duração sugerida | Quem | Resultado |
| --- | --- | --- | --- |
| A. Preparação técnica | 2–3 dias | TI / quem publica | Ambiente no ar com HTTPS, banco PostgreSQL, backup, fotos |
| B. Ensaio interno | 1 semana | RH + 3 a 5 pessoas da equipe do projeto | Falhas encontradas e corrigidas, sem valor legal |
| C. Piloto | 4 semanas (1 mês fechado) | 1 unidade/setor, 10 a 30 pessoas | Um fechamento mensal completo, com relatório de lições |
| D. Expansão | por ondas | demais setores | Uso em toda a empresa |

**Regra de ouro do piloto:** continue com o sistema anterior (papel, planilha ou REP atual) **em paralelo** até o primeiro fechamento conferido. Só desligue o antigo depois de decisão registrada.

## 2. Fase A: preparação técnica

Siga `deploy/README.md`. Lista de conferência:

1. **Servidor e domínio:** máquina com Docker, DNS apontando, portas 80/443. HTTPS é automático (Caddy). A câmera e o GPS do navegador **só funcionam em HTTPS**.
2. **`.env`:** preencher `PONTO_IMAGE` (versão fixa), `DOMAIN`, senhas do banco, `SECRET_KEY`, `TOTP_KEY` (guardar com o mesmo cuidado do backup), `REQUIRE_2FA_ROLES=hr,admin`.
3. **Fotos:** escolher `PHOTO_STORE`. Para o piloto, `local` (volume) basta; se `s3`, rodar `docker compose exec app python -m app.photos_check` e conferir que o bucket é **privado**.
4. **Migrações no PostgreSQL:** subir com `docker compose up` e conferir que o serviço `migrate` termina sem erro (0001 a 0009) e que o papel restrito `ponto_app` recebeu as permissões (`deploy/postgres-roles.sql`, incluindo `punch_photos`, `kiosks`, `kiosk_tickets`). Já rodou com sucesso em PostgreSQL 18 local; no servidor, o que resta validar é o fluxo em contêineres.
5. **Testes em PostgreSQL:** `PONTO_TEST_DATABASE_URL=postgresql+psycopg://<dono>@<host>:<porta>/<banco_de_teste>` e `pytest` (230 testes, nenhum ignorado; usar um banco de teste descartável).
6. **Backup e restauração:** ver `deploy/backup`. **Faça uma restauração de teste em outra máquina** e anote o tempo. Backup que nunca foi restaurado não conta.
7. **Relógio:** `CLOCK_CHECK_ENABLED=true`; o app **recusa batida online** se o relógio do servidor divergir mais de 30 s da Hora Legal (NTP.br, porta UDP 123 de saída precisa estar liberada). Conferir logo no início: no teste local o relógio do Windows estava 90 s adiantado e o sistema recusou as batidas, como deveria. No servidor, use `chrony`/`systemd-timesyncd` e monitore o desvio.
8. **Conformidade:** `INPI_NUMBER`, `DEV_ID/NAME/EMAIL` e certificado ICP-Brasil só existem após o registro. **Sem eles, o app roda em modo de teste** (arquivos e comprovantes saem marcados como TESTE). Isso é aceitável no ensaio, **não** no piloto com valor legal (ver seção 7).
9. **Primeiro acesso:** criar a empresa e o administrador (`python -m app.seed ...`), ativar 2FA do administrador, cadastrar jornadas, importar pessoas por CSV (coluna `codigo` opcional) e distribuir as senhas temporárias por canal seguro.
10. **Monitoramento mínimo:** alguém olha, todo dia útil, a aba Gestão > Fiscalização e as Centrais (aviso de "sem sinal"); um alerta externo no endereço `/` do domínio.

**Critério de saída:** login, batida, espelho, fechamento de um mês de teste, foto e backup restaurado funcionando no ambiente real.

## 3. Fase B: ensaio interno (uma semana)

Roteiro de testes práticos (marcar cada item; anotar o que falhar com aparelho, navegador e horário):

**Aplicativo do colaborador**
- [ ] Instalar no celular (Android/Chrome e iPhone/Safari) e abrir sem internet. *Sabemos que o Chrome do Android já falhou em oferecer "Instalar app" em um teste: investigar com o domínio real em HTTPS.*
- [ ] Batidas 1ª a 4ª, mensagem "Jornada encerrada" e ausência da 5ª.
- [ ] Batida sem internet, envio depois, comprovante.
- [ ] Foto com consentimento; negar a câmera e conferir que a batida ocorre sem foto.
- [ ] Meu crachá (QR) em tela cheia; definir/trocar PIN.

**Central (tablet real; ver seção 4)**
- [ ] Pareamento; tela cheia; tela ligada por horas; reabrir após reiniciar o tablet.
- [ ] Leitura de QR do celular e do crachá impresso (distâncias, luz do dia, luz baixa).
- [ ] Código interno e CPF; PIN (com e sem exigência); bloqueio após 5 erros.
- [ ] Foto obrigatória: câmera negada e câmera lenta.
- [ ] GPS: dentro e fora do raio (verificar em Relatórios > Divergências da Central).
- [ ] Sem internet (Wi-Fi desligado): só o QR do crachá impresso registra ("Batida guardada"); com a rede de volta, a fila zera e a batida aparece em Relatórios > Batidas por origem. Testar também crachá regenerado, pessoa sem consentimento e leitor USB.
- [ ] Fluxo de pico: 10 pessoas em fila; medir segundos por pessoa.

**Gestão / RH**
- [ ] Ajustes (esqueci de bater), aprovação, ausências, banco de horas.
- [ ] Fechamento do mês; conferir que as **fotos foram apagadas** ao fechar.
- [ ] Relatórios (todos) e o Espelho oficial em PDF; abrir os arquivos no Excel/leitor de PDF usados pelo RH.
- [ ] AFD/AEJ (em modo de teste) abrem no validador que o contador usa.
- [ ] Impressão de crachás em papel (A4, 8 por página): tamanho, corte, QR legível pela Central.
- [ ] Política "só a Central" para uma pessoa.

**Critério de saída:** nenhum defeito bloqueante aberto; lista de melhorias priorizada.

## 4. Tablet da Central: ficha técnica e preparo

- **Aparelho:** tablet Android ou iPad com câmera frontal decente e GPS; 10" ou mais. Recomendado carregador fixo e suporte que não permita levar o aparelho.
- **Navegador:** Chrome (Android) ou Safari (iPad). Abrir `https://<domínio>/central`, parear, e usar "Adicionar à tela inicial" / instalar como "Ponto Central".
- **Ajustes do sistema (à mão, não há como o app fazer):** tempo de tela desligada = nunca (ou o `wakeLock` do app; conferir), brilho fixo, atualizações automáticas fora do horário de uso, modo "fixar app" (Android) ou Acesso Guiado (iPad) para impedir sair da tela, permissão de câmera e localização já concedidas ao domínio.
- **Posto:** cadastrar em Gestão > Centrais com latitude/longitude e raio (100 m é o padrão). Use "Usar minha localização atual" com o tablet no local.
- **Rede:** Wi-Fi estável; a Central não registra sem internet nesta versão. Defina um plano B para a unidade (ver seção 6).
- **Segurança física:** o aparelho pareado é uma credencial. Se sumir, **revogar em Gestão > Centrais na hora**.
- **Limite:** até 5 centrais ativas por empresa.

## 5. Fase C: piloto (um mês)

**Escolha da unidade:** um setor com gestor engajado, bom Wi-Fi, mistura de quem usa celular e quem usará a Central. Evite começar por turno noturno (regra de virada de meia-noite é a mais delicada; incluir depois, em onda própria).

**Semana 0 (antes de começar)**
- Comunicar a equipe: o que é, para que serve a foto, por que o consentimento (LGPD), como corrigir esquecimentos (Ajustes), a quem recorrer.
- Cadastrar as pessoas com **jornada correta** e imprimir/entregar crachás e senhas temporárias.
- Treino de 15 minutos por grupo, com a Central presente.
- Definir o **plano de contingência** (seção 6) e o contato de suporte.

**Semanas 1–4: rotina**
- Diária (RH, 5 min): Fiscalização, Centrais "sem sinal", pedidos de Ajuste pendentes.
- Semanal: relatório Batidas por origem e Divergências da Central; reunião de 15 min com o gestor do setor.
- Registrar num quadro simples: incidente, data, impacto, correção, dono.

**Fim do mês: fechamento**
- Conferir o Espelho de cada pessoa contra o controle paralelo (papel/planilha/REP antigo). Registrar diferenças e a causa de cada uma.
- Fechar o mês; conferir a purga das fotos; gerar AFD/AEJ e fazer um download de auditoria.
- Testar uma **restauração de backup** com dados reais do piloto.

**Métricas de sucesso (sugestão; ajuste ao seu contexto)**

| Métrica | Meta |
| --- | --- |
| Diferença entre o espelho e o controle paralelo, por pessoa | ≤ 5 min/dia em 95% dos dias, e cada diferença explicada |
| Pessoas que conseguem bater sem ajuda após a semana 1 | ≥ 90% |
| Falhas de foto/câmera na Central | < 3% das batidas |
| Batidas na Central fora do raio | < 2% (senão revisar posto/raio) |
| Tempo por pessoa na Central | ≤ 15 s |
| Ajustes por "esqueci de bater" | em queda a partir da semana 2 |
| Incidentes de indisponibilidade | 0 no horário de entrada/saída |

**Critério de saída (vai/não vai):** todas as metas atingidas ou desvios aceitos por escrito; nenhum incidente de segurança; restauração de backup validada; parecer jurídico/contábil favorável (seção 7).

## 6. Contingência

| Situação | O que fazer |
| --- | --- |
| Internet da unidade cai | Quem tem celular: bate pelo aplicativo (fica guardado e é enviado depois, dentro de `OFFLINE_MAX_HOURS`). Na Central, só o QR do crachá impresso registra (fica na fila e é enviado depois); código, CPF e QR do aplicativo não. Se a empresa exige PIN, a Central não registra offline: usar o controle paralelo e lançar depois via Ajustes. |
| Central com defeito ou sem sinal | Revogar/refazer pareamento em Gestão > Centrais; enquanto isso, aplicativo. |
| Tablet perdido/roubado | Revogar a Central imediatamente; revisar batidas do período em Divergências da Central. |
| Crachá perdido | Regenerar o crachá da pessoa (o QR antigo deixa de valer) e reimprimir. |
| Suspeita de PIN/código vazado | "Zerar PIN" e regenerar crachá; considerar exigir PIN para toda a empresa. |
| Servidor indisponível | Restaurar do backup; batidas no aplicativo com fila local reenviam depois. Registrar o período fora do ar. |
| Erro em batida já feita | Nunca editar: Ajustes (desconsiderar/incluir) com aprovação; a trilha é imutável por desenho. |

## 7. Pendências legais e de homologação (não técnicas)

Sem estas, o uso **não** deve ser tratado como REP-P regular:

- **Registro do programa no INPI** e número no `INPI_NUMBER`; identificação do desenvolvedor.
- **Certificado ICP-Brasil** para assinar comprovantes e arquivos.
- **Hipóteses a validar com o jurídico/contabilidade:** H1 a H8 do projeto (incluindo H7, registro sem internet, e H8, código de coletor `04` para a Central).
- **Texto de consentimento da foto** e base legal da coleta de foto e localização (LGPD); definir com o jurídico/DPO o prazo (hoje até o fechamento mensal), o acesso (só RH/admin) e a política de privacidade.
- **Acordo coletivo/portaria interna** sobre a forma de registro, se aplicável; comunicação formal aos empregados.
- **Validação dos arquivos AFD/AEJ** em validador oficial ou pelo contador antes de qualquer fiscalização.
- **Revisão de acessibilidade e contraste** das telas (adiada a pedido; deve ocorrer antes da expansão).

## 8. Fase D: expansão

- Ondas de 1 setor por vez, cada uma com semana 0 (comunicação e treino) e revisão após 2 semanas.
- Turnos noturnos: usar a opção "jornada cruza a meia-noite" e validar espelho e horas noturnas com o contador.
- Após a expansão: rotina de revisão trimestral de Centrais (posto, raio, aparelhos), crachás e acessos; teste de restauração semestral.

## 9. Riscos conhecidos e responsáveis (preencher)

| Risco | Probabilidade | Impacto | Mitigação | Dono |
| --- | --- | --- | --- | --- |
| Migração 0006–0009 falhar em PostgreSQL | média | alto | Fase A itens 4–5, com banco descartável antes | |
| Câmera/GPS do tablet inadequados | média | médio | Teste na Fase B; trocar o aparelho | |
| Resistência à foto | média | médio | Comunicação e consentimento; política "só aplicativo" para exceções | |
| Wi-Fi instável na Central | média | alto | Plano B; considerar Central offline (fase 6) | |
| Falta de INPI/certificado no início | alta | alto | Piloto em paralelo ao sistema atual | |
| Perda do `TOTP_KEY` ou do backup | baixa | alto | Cofre de segredos; restauração testada | |
