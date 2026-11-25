# Ensaio completo (fase B): passo a passo

Na VM (`https://ponto.wasadocs.com.br`), com cinco tipos de pessoa, no computador, no celular e no tablet da Central.
Duração: 2 a 3 horas, com 2 ou 3 pessoas. Os dados são de ensaio: na entrada em produção o banco começa **novo**.

## 0. Preparar (uma vez, uns 20 minutos)

**Relógio da VM:** `chronyc tracking` deve mostrar "System time" abaixo de 1 s (o app recusa batida com desvio maior que 30 s).

**Pessoas.** Entre com a sua conta (Administrador, só gestão) e, em **Gestão > Cadastros > Pessoas > Cadastrar uma pessoa**, deixe a empresa assim
(use CPFs válidos; para o ensaio pode usar os de teste abaixo):

| Persona | Ponto | Acesso | Funções | Gestor | Onde testa |
| --- | --- | --- | --- | --- | --- |
| **Você** (já existe) | não registra | Google | Administrador | — | computador |
| **Gil** (gestor) | registra, jornada Comercial | e-mail e senha | Gestor | — | celular |
| **Rita** (RH) | registra, jornada Comercial | e-mail e senha | RH | — | computador |
| **Ana** (colaboradora) | registra, jornada Comercial, banco de horas | e-mail e senha, "Aplicativo e Central" | — | Gil | celular |
| **Zeca** (só Central) | registra, jornada Comercial | **sem** acesso ao app | — | Gil | tablet |

CPFs válidos para teste: 111.444.777-35, 390.533.447-05, 168.995.350-09, 935.411.347-80, 123.456.789-09.

**Jornada.** Em Cadastros > Jornadas, crie "Comercial" (seg a sex, 8h, intervalo 1h às 12:00) **antes** de cadastrar as pessoas.

**Central.** Cadastros > Centrais > *Cadastrar uma central* (CT-01; "Usar minha localização atual" estando no local do tablet; raio 100).
Anote o **código de pareamento** (aparece uma vez, vale 15 minutos). No tablet, abra `https://ponto.wasadocs.com.br/central` e digite o código.

**Crachás.** Cadastros > Pessoas > "Crachás de todos (PDF)": imprima uma vez em papel comum.

## 1. Como registrar o resultado

Para cada item: **OK**, **FALHA** ou **N/A**. Se falhar: aparelho, navegador, o que fez, o que apareceu e a hora. Foto ou gravação de tela
ajuda muito. Me mande a lista (pode ser só o que falhou e o que achou estranho, mesmo que "funcione").

## 2. O que cada pessoa vê (5 minutos por persona)

Entre como cada pessoa e confira o menu. **Ver algo que não deveria é FALHA.**

| # | Persona | Deve ver | Não deve ver |
| --- | --- | --- | --- |
| V1 | Você | Só a Gestão: Painel, Aprovações, Espelhos, Banco de horas, Ausências, Relatórios, Cadastros, Empresa (com Configurações e Auditoria) | Ponto, Registros, Solicitações; em Minha conta, o bloco "Central do Ponto" |
| V2 | Gil | Seletor "Meu ponto / Gestão". Gestão: Painel, Aprovações, Espelhos, Banco de horas, Ausências, Relatórios (só a equipe: Ana e Zeca) | Cadastros, Empresa; Rita no Painel |
| V3 | Rita | Meu ponto e Gestão; Gestão com Cadastros e Empresa (só Fechamento e Fiscalização) | Configurações, Auditoria, funções de gestão no cadastro |
| V4 | Ana | Só Meu ponto: Ponto, Registros, Solicitações, Banco de horas | Qualquer item de Gestão |
| V5 | Zeca | Não consegue entrar no app (e-mail e senha não existem para ele) | — |

## 3. Login e conta

| # | Teste | Esperado |
| --- | --- | --- |
| L1 | Você: sair e "Fazer login com o Google" | Entra direto no Painel |
| L2 | Ana: entrar com a senha temporária | Pede para criar uma senha nova antes de qualquer coisa |
| L3 | Ana: Minha conta > "Continuar com o Google" com uma conta Google qualquer dela | "Conta Google vinculada"; depois entra pelo botão do Google |
| L4 | Uma conta Google não cadastrada tenta entrar | "A conta Google … não está cadastrada" |
| L5 | Você: Empresa > Configurações > Login > desmarcar "Permitir também entrar com e-mail e senha"; Gil tenta entrar com senha | Gil recebe "Nesta empresa o acesso é pelo botão Entrar com Google". **Religue a opção depois** |
| L6 | Rita: Minha conta > ativar 2FA, sair e entrar com senha | Pede o código do autenticador |
| L7 | Abrir `/privacidade` e `/termos` sem estar logado | As páginas abrem |

## 4. Meu ponto no celular (Ana)

Aparelhos: pelo menos um Android (Chrome) e, se houver, um iPhone (Safari).

| # | Teste | Esperado |
| --- | --- | --- |
| A1 | Menu do navegador > **Instalar app** / **Adicionar à tela inicial** | Instala. **Anote se a opção aparece** |
| A2 | Abrir o app instalado sem internet (modo avião) | Abre |
| A3 | **Registrar ponto** com internet | Aparece em "Hoje"; próxima batida "Intervalo" |
| A4 | Sem internet: registrar ponto; depois religar | "Guardado, aguardando envio"; ao religar, envia sozinho |
| A5 | Empresa > Configurações (você) ligar "Foto na batida"; Ana autoriza e registra | Câmera abre; batida registrada |
| A6 | Ana nega a câmera do navegador e registra | Batida registrada **sem** foto, sem travar |
| A7 | Registros: o mês, os comprovantes (PDF) e "Pedir correção deste dia" | Abre Solicitações já com a data |
| A8 | Solicitações > Corrigir marcação > "Esqueci de bater" | Pedido aparece em "Meus pedidos" como Pendente |
| A9 | Solicitações > Atestado ou abono (um dia, parte do dia) | Pedido Pendente; dá para cancelar |
| A10 | Banco de horas | Saldo e extrato (desde hoje) |
| A11 | Minha conta > Central do Ponto: definir PIN 7391; **Meu crachá (QR)** | "PIN salvo" (1234 é recusado); QR troca a cada 30 s |

## 5. Gestor (Gil, no celular)

| # | Teste | Esperado |
| --- | --- | --- |
| G1 | Gestão > Aprovações: aprovar o ajuste da Ana (A8) e rejeitar o atestado (A9) com motivo | Some da caixa; Ana vê "Aprovado"/"Rejeitado" com a resposta |
| G2 | Espelhos > Ana | O ajuste aprovado aparece no dia |
| G3 | Painel | Só Ana e Zeca, com a situação de agora |
| G4 | Meu ponto: Gil registra o ponto e pede um ajuste | Funciona como para a Ana; o pedido **não** aparece na caixa dele (vai para RH/Administração) |

## 6. RH (Rita, no computador)

| # | Teste | Esperado |
| --- | --- | --- |
| R1 | Aprovações: aprovar o ajuste do Gil (G4) | Aprovado |
| R2 | Ausências > Registrar ausência: férias da Ana (próxima semana) | Entra já aprovada; aparece no espelho dela |
| R3 | Banco de horas > Ana > Fazer um lançamento (crédito 1h) | Saldo muda; "Lançamento" no extrato |
| R4 | Cadastros > Pessoas: editar a Ana (cargo, admissão, gestor) | Salva; o gestor só pode ser quem tem função de gestão |
| R5 | Tentar editar o Gil | "Só a Administração altera quem tem função de gestão" |
| R6 | Relatórios: Fechamento mensal, Batidas por origem, Divergências da Central (PDF e CSV) | Baixam e abrem |
| R7 | Empresa > Fiscalização: AFD e AEJ; Verificar integridade | Baixam (marcados TESTE); "Íntegro" |

## 7. Central no tablet (Zeca e Ana)

| # | Teste | Esperado |
| --- | --- | --- |
| C1 | Pareamento e tela cheia; instalar como "Ponto Central" | "Central · CT-01", relógio grande, "Conectada" |
| C2 | Deixar 30 minutos parado | A tela não apaga (ou anote quando apaga) |
| C3 | **Crachá impresso** do Zeca na câmera, a uns 30 cm | Lê em poucos segundos; anote distância e luz que funcionam |
| C4 | **QR do app** da Ana (Meu crachá) | Lê |
| C5 | Código interno e CPF do Zeca | Identifica; o CPF some da tela em 3 s |
| C6 | Confirmar > foto (contagem de 3 s) | "Batida registrada", NSR e hora |
| C7 | Câmera negada no navegador do tablet | Mensagem clara; nada é registrado |
| C8 | Tablet a mais de 100 m do posto | Batida ok; aparece em Divergências como "fora do posto" |
| C9 | Fila: 3 pessoas seguidas, com cronômetro | Segundos por pessoa (meta: até 15 s) |
| C10 | Sem internet: crachá impresso | "Batida guardada"; ao religar, a fila zera sozinha |
| C11 | Sem internet: QR do app, código ou CPF | Recusa com explicação (só o crachá impresso vale) |
| C12 | Você regenera o crachá do Zeca; ler o crachá antigo | Recusa |
| C13 | Você muda a Ana para "Só na Central"; ela tenta registrar pelo app | O app explica que o ponto dela é só na Central; na Central ela bate normalmente |

## 8. Administração (você, no computador)

| # | Teste | Esperado |
| --- | --- | --- |
| D1 | Empresa > Configurações: dados da empresa (local de trabalho), regras do banco de horas, PIN da Central | Salvam; a Central passa a pedir o PIN |
| D2 | Cadastros > Pessoas: dar a função Gestor à Ana (e depois tirar) | Ana passa a ter o seletor "Meu ponto / Gestão", sem ninguém na equipe; ao tirar, volta a ver só Meu ponto |
| D3 | Desativar o Zeca; tentar a Central com o crachá dele | Recusa; Zeca some do Painel |
| D4 | Empresa > Fechamento: fechar o mês anterior | Fecha; as fotos daquele mês somem; pedidos daquele mês ficam bloqueados |
| D5 | Empresa > Auditoria | Eventos legíveis (aprovações, cadastros, login com Google) |

## 9. O que observar além dos testes

- Texto confuso, botão pequeno para o dedo, tela que trava ou demora.
- Alguém que não soube o que fazer sem ajuda: anote **quem** e **em qual tela**.
- Contraste ruim ou letra pequena (a revisão de acessibilidade ainda está pendente).
- Foto escura, cortada ou desfocada; tempo até a foto ficar boa.
- Tablet esquentando, perdendo o Wi-Fi ou com a bateria caindo rápido.

## 10. Encerrar

Me envie o resultado. Eu classifico cada ponto como defeito (corrijo), melhoria (priorizo) ou ajuste de texto/tela.

**Critério de saída da fase B** (ver `docs/piloto-e-implantacao.md`): nenhum defeito bloqueante aberto e a lista de melhorias priorizada.
Na entrada em produção, o banco de ensaio é descartado e a empresa real é criada do zero (`python -m app.seed ... --so-gestao`).
