# Ensaio interno (fase B): passo a passo

Duração: 1 a 2 horas para o roteiro completo, com 2 a 3 pessoas. Objetivo: achar o que só aparelhos reais mostram. Nada aqui tem valor legal (dados de demonstração, modo de teste).

## 0. Antes de começar (5 minutos)

1. **Acerte o relógio do Windows.** Hoje ele está ~90 s adiantado em relação à Hora Legal (NTP.br) e, com o limite de 30 s, **o sistema recusa toda batida online** ("Relógio do servidor fora de sincronismo…"). Em um PowerShell **como administrador**:
   ```powershell
   w32tm /resync
   ```
   Confira: `w32tm /stripchart /computer:a.st1.ntp.br /samples:1 /dataonly` deve mostrar menos de 1 s.
2. **Servidor de ensaio.** Já está no ar em `http://localhost:8780`, com banco próprio (`C:\ponto\ensaio.db`, não mexe no seu `local.db`) e dados de demonstração. Para subir de novo depois de reiniciar o PC:
   ```powershell
   powershell -ExecutionPolicy Bypass -File run-local.ps1 -Port 8780 -Demo -DbFile C:\ponto\ensaio.db
   ```
   (Sem `-Reset`, o banco é preservado. Com `-Reset` volta ao zero.)
3. **Túnel HTTPS** (câmera e GPS só funcionam em HTTPS). Em outro terminal:
   ```powershell
   cloudflared tunnel --url http://localhost:8780
   ```
   Ele imprime um endereço `https://….trycloudflare.com`. Use esse endereço no celular e no tablet. O endereço muda a cada vez.
4. **Crachás de teste:** `C:\ponto\ensaio\crachas-demo.pdf` (8 por página A4). Imprima **uma vez** em papel comum para os testes de leitura.

**Logins** (senha `senha-forte-123` para todos): `admin@demo.com` (administrador), `rita@demo.com` (RH), `gil@demo.com` (gestor), `ana@demo.com`, `beto@demo.com`, `carla@demo.com` (colaboradores).

## 1. Como registrar o resultado

Para cada item: **OK**, **FALHA** ou **N/A**. Se falhar, anote: aparelho, navegador, o que você fez, o que apareceu, hora. **Foto ou gravação de tela ajuda muito.** No fim, me mande a lista (pode ser só o que falhou e o que você achou estranho, mesmo que "funcione").

## 2. Aplicativo no celular (usar Ana)

Aparelhos: pelo menos um Android (Chrome) e, se houver, um iPhone (Safari).

| # | Teste | Esperado |
| --- | --- | --- |
| A1 | Abrir o endereço do túnel e entrar como Ana | Entra; saudação "Bom dia/Boa tarde, Ana" |
| A2 | Menu do navegador: **Instalar app** / **Adicionar à tela inicial** | Instala. **Anote se "Instalar app" aparece** (no seu Chrome já falhou uma vez) |
| A3 | Abrir o app instalado; desligar Wi-Fi e dados; abrir de novo | Abre sem internet |
| A4 | **Registrar ponto**, uma vez | Aparece a próxima batida em "Hoje"; mostra "1ª · Entrada" |
| A5 | Sem internet: registrar ponto | "Guardado, aguardando envio"; ao religar, envia sozinho |
| A6 | Consentir a foto e registrar de novo | Câmera abre; foto tirada; batida registrada |
| A7 | Negar a câmera do navegador e registrar | Batida registrada **sem** foto, sem travar |
| A8 | Chegar à 4ª batida | Botão "Jornada encerrada", desativado |
| A9 | Minha conta > **Central do Ponto**: definir PIN 7391 | "PIN salvo"; 1234 é recusado |
| A10 | **Meu crachá (QR)** | QR em tela cheia, contagem "Muda em N s", troca a cada 30 s |
| A11 | Espelho: abrir o mês | Batidas do dia aparecem com origem "Aplicativo" |
| A12 | Ajustes: pedir "Esqueci de bater" | Pedido criado, aparece para o gestor |

## 3. Central no tablet (ou no celular, se não houver tablet)

**Preparar (uma vez):** entre como `admin@demo.com` no computador > Mais > Gestão > **Centrais** > *Cadastrar uma central* (nome CT-01, botão "Usar minha localização atual" no computador, raio 100). Anote o **código de pareamento** (aparece uma vez, vale 15 min).

No tablet, abra `<endereço do túnel>/central`, digite o código.

| # | Teste | Esperado |
| --- | --- | --- |
| C1 | Pareamento | Aparece "Central · CT-01", relógio grande, "Conectada" |
| C2 | Tela cheia (botão no rodapé); instalar como "Ponto Central" | Funciona; anote se instala |
| C3 | Deixar 30 min parado | A tela **não apaga** (ou anote quando apaga) |
| C4 | Aproximar o **crachá impresso** (QR) da câmera, a ~30 cm | Lê em poucos segundos. Teste perto/longe e luz forte/fraca; anote a distância que funciona |
| C5 | Mostrar o **QR do app** (Meu crachá) do celular | Lê |
| C6 | Digitar **código interno** (Mais > Minha conta, ou Gestão > Pessoas) | Identifica |
| C7 | Digitar **CPF** | Identifica; o CPF some da tela depois de 3 s |
| C8 | Confirmar > foto (contagem de 3 s) | Foto tirada; "Batida registrada", NSR, hora |
| C9 | **Câmera negada** (Configurações do navegador) | Mensagem clara; **nada é registrado** |
| C10 | **GPS**: negar a localização | A batida acontece (fica "sem localização" nas divergências) |
| C11 | Levar o tablet a mais de 100 m do posto e bater | Batida ok; sinaliza "fora do posto" no relatório |
| C12 | Fila: 3 pessoas seguidas, com cronômetro | Anote segundos por pessoa (meta: ≤ 15 s) |
| C13 | Deixar a tela de identificação 30 s sem tocar | Volta sozinha ao início |
| C14 | **Sem internet** (Wi-Fi do tablet desligado): ler **crachá impresso** | "Batida guardada"; selo "1 batida aguardando envio" |
| C15 | Sem internet: tentar **QR do app**, código ou CPF | Recusa com explicação (só o crachá vale) |
| C16 | Ligar o Wi-Fi | A fila zera sozinha; batida aparece no relatório "Batidas por origem" |
| C17 | Leitor USB/Bluetooth em modo teclado (se tiver) | Lê o crachá na espera, sem tocar na tela |

## 4. Gestão e RH (no computador, usar Rita e o admin)

| # | Teste | Esperado |
| --- | --- | --- |
| G1 | Gestão > Pessoas > Ana: código, PIN, **Baixar crachá (PDF)** | Baixa; QR nítido |
| G2 | **Crachás de todos (PDF)**, impressão em A4 | 8 por folha, corte fácil; **QR impresso é lido pela Central (C4)** |
| G3 | **Regenerar crachá** da Ana; ler o crachá antigo na Central | Recusa (crachá antigo não vale) |
| G4 | Ana "Bate ponto em: Só a Central"; tentar pelo app | App bloqueado com explicação; Central continua |
| G5 | Gestão > Centrais: última vez vista, batidas de hoje | Bate com o que você fez; aviso se ficar sem sinal |
| G6 | Relatórios > **Batidas por origem** (CSV e PDF) | Abre no Excel/leitor de PDF; origem "Central CT-01" |
| G7 | Relatórios > **Divergências da Central** | Mostra o "fora do posto" (C11), "sem localização" (C10) e batida sem internet recusada, se houver |
| G8 | Aprovar um Ajuste da Ana | Aparece no espelho |
| G9 | **Fechar o mês anterior** (Gestão > Fechamento) | Fecha; **as fotos daquele mês somem** |
| G10 | Gestão > Fiscalização: AFD e AEJ | Baixa; marcado como TESTE |
| G11 | Auditoria | Eventos legíveis ("Batida na Central", "Central pareada"…) |

## 5. O que observar além dos testes

- Qualquer texto confuso, botão pequeno para o dedo, ou tela que "trava".
- Alguém que não soube o que fazer sem ajuda (anote **quem** e **em qual tela**).
- Cansaço visual, contraste ruim, letra pequena (a revisão de acessibilidade está pendente; anote aqui).
- Tempo até a foto ficar boa; foto escura, cortada ou desfocada.
- Se o tablet esquenta, some o Wi-Fi, ou a bateria cai rápido.

## 6. Encerrar o ensaio

- Feche o túnel (Ctrl+C no terminal do `cloudflared`). O endereço deixa de existir.
- Os dados ficam em `C:\ponto\ensaio.db` (fora do git). Para apagar: `run-local.ps1 -Port 8780 -Reset -DbFile C:\ponto\ensaio.db` e depois encerre o servidor.
- Me envie o resultado. Eu classifico o que for defeito (corrijo), melhoria (priorizo) ou ajuste de texto/tela.

**Critério de saída da fase B** (ver `docs/piloto-e-implantacao.md`): nenhum defeito bloqueante aberto e a lista de melhorias priorizada.
