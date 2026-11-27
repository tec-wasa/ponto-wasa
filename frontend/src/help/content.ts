/**
 * Manual do aplicativo (tela Ajuda). Um tópico por assunto, agrupados; cada um diz ONDE fica, O QUE é e COMO se faz.
 * Texto simples com **negrito**. Ao mudar uma tela, atualize o tópico dela aqui.
 */
import type { Permission } from "../types";

export interface Block {
  h?: string; // subtítulo
  text?: string; // parágrafo
  steps?: string[]; // passo a passo numerado
  list?: string[]; // itens sem ordem
  tip?: string; // dica
  warn?: string; // atenção
}

export interface Topic {
  id: string;
  group: string;
  title: string;
  who: string; // para quem é (texto)
  need?: Permission[]; // aparece em "Para mim" se a pessoa tiver alguma destas permissões (vazio = todos)
  where?: { path: string; label: string }; // a tela, para o botão "Abrir esta tela"
  summary: string;
  blocks: Block[];
}

export const GROUPS = [
  "Comece por aqui",
  "Meu ponto",
  "Gestão do dia a dia",
  "Cadastros",
  "Empresa",
  "Central do Ponto (tablet)",
  "Dúvidas e glossário",
];


export const TOPICS: Topic[] = [
  // ───────────────────────────── Comece por aqui ─────────────────────────────
  {
    id: "organizacao",
    group: "Comece por aqui",
    title: "Como o aplicativo é organizado",
    who: "Todos",
    summary: "As duas áreas (Meu ponto e Gestão), os menus no computador e no celular, Minha conta e este manual.",
    blocks: [
      {
        h: "As duas áreas",
        list: [
          "**Meu ponto**: para quem registra ponto. Tem as telas Ponto (bater o ponto), Registros (espelho do mês e comprovantes), Solicitações (pedir correções e enviar atestados) e Banco de horas.",
          "**Gestão**: para quem tem função de Gestor, RH ou Administração. Tem Painel, Aprovações, Espelhos, Tratamento, Banco de horas, Ausências, Relatórios, Cadastros e Empresa (cada pessoa vê só o que a função dela permite).",
          "Quem tem as duas coisas (por exemplo, uma administradora que também bate ponto) vê no topo a chave **Meu ponto | Gestão** para trocar de área.",
          "Quem só faz gestão (não registra ponto) entra direto na Gestão. Quem só registra ponto vê apenas Meu ponto.",
        ],
      },
      {
        h: "Onde ficam os menus",
        list: [
          "**No computador**: os itens da área ficam na barra do topo, ao lado do nome Ponto.",
          "**No celular**: as três telas principais ficam na barra de baixo; o restante fica em **Mais** (último botão da barra de baixo).",
          "**Bolinha com as suas iniciais** (canto superior direito): abre Minha conta (senha, conta Google, verificação em duas etapas, crachá e Sair).",
          "**Sol/Lua** (ao lado das iniciais): alterna entre tema claro e escuro.",
          "**Ajuda**: no computador, o botão **?** ao lado do tema abre este manual; no celular, use Mais > **Ajuda**. A tela de entrada também tem o link Ajuda.",
        ],
      },
      {
        h: "Funções de cada pessoa",
        list: [
          "**Colaborador** (sem função de gestão): registra o próprio ponto e acompanha os próprios registros.",
          "**Gestor**: acompanha a própria equipe (as pessoas em que ele aparece como gestor) e aprova os pedidos dela.",
          "**RH**: cadastros, jornadas, ausências, banco de horas, fechamento do mês, relatórios e arquivos fiscais da empresa toda.",
          "**Administração**: tudo o que o RH faz, mais dados da empresa, configurações, centrais, funções das pessoas e auditoria.",
          "As funções se somam: a mesma pessoa pode ser Administração, RH e Gestor, e também registrar ponto.",
        ],
      },
    ],
  },
  {
    id: "primeiro-acesso",
    group: "Comece por aqui",
    title: "Primeiro acesso de quem bate ponto",
    who: "Colaboradores",
    need: ["punch"],
    where: { path: "/", label: "Ponto" },
    summary: "Do primeiro login até a primeira batida: entrar, criar a senha, instalar o app e autorizar localização e foto.",
    blocks: [
      {
        steps: [
          "Receba da empresa o endereço do aplicativo e a forma de entrar: **e-mail e senha temporária** ou **conta Google** (com o mesmo e-mail cadastrado).",
          "Abra o endereço no navegador do celular e toque em **Entrar com Google**, ou em **Entrar com e-mail e senha** e digite os dados recebidos.",
          "Se entrou com senha temporária, o app abre Minha conta pedindo uma **senha nova** (mínimo de 10 caracteres, com letras e números; não use o e-mail nem o CPF). Digite a senha atual (a temporária), a nova duas vezes e toque em **Trocar senha**.",
          "Instale o app na tela inicial do celular (veja o tópico **Instalar o aplicativo**). Assim ele abre como um aplicativo comum e funciona mesmo sem internet.",
          "Na tela **Ponto**, o app pergunta se pode registrar a sua **localização** junto com o ponto. É opcional: toque em **Permitir** ou em **Agora não**.",
          "Se a empresa usa foto na batida, o app também pergunta se pode **tirar uma foto a cada batida**. É opcional; se recusar ou a câmera falhar, o ponto é registrado do mesmo jeito.",
          "Toque em **Registrar ponto** para a sua primeira batida (a entrada). Pronto.",
        ],
      },
      {
        tip: "Vincule a sua conta Google em Minha conta > Como você entra: depois disso basta um toque para entrar, sem digitar senha.",
      },
      {
        warn: "Se a empresa marcou que você bate ponto **só na Central** (o tablet da empresa), o botão Registrar ponto fica bloqueado no app. O app continua mostrando seus registros, comprovantes e pedidos.",
      },
    ],
  },
  {
    id: "implantacao",
    group: "Comece por aqui",
    title: "Implantação passo a passo (primeiro administrador)",
    who: "Administração",
    need: ["company.settings"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "A ordem recomendada para deixar a empresa pronta: dados, feriados, jornadas, pessoas, gestores, centrais, crachás e login.",
    blocks: [
      {
        text: "Siga nesta ordem: cada passo usa o anterior. Cada item tem um tópico próprio neste manual com os detalhes.",
      },
      {
        steps: [
          "**Dados da empresa**: Gestão > Empresa > Configurações > Empresa. Confira a razão social, o local de prestação do serviço (endereço), CAEPF/CNO se houver e o **fuso horário** (Salvador: America/Bahia). Toque em **Salvar dados da empresa**.",
          "**Feriados**: na mesma tela, quadro Feriados. Os nacionais já vêm prontos. Decida sobre Carnaval e Corpus Christi e cadastre os estaduais e municipais.",
          "**Banco de horas** (se a empresa usa): quadro Banco de horas, com o limite do saldo e o prazo para compensar.",
          "**Jornadas**: Gestão > Cadastros > Jornadas > **Criar uma jornada**. Crie uma para cada horário diferente (ex.: Comercial 08h–17h seg–sex).",
          "**Pessoas**: Gestão > Cadastros > Pessoas. Cadastre uma a uma em **Cadastrar uma pessoa**, ou várias de uma vez em **Importar várias pessoas por CSV**. Informe a data de admissão e a jornada de cada uma.",
          "**Gestores e funções**: edite as pessoas que vão gerir e marque as funções (Gestor, RH, Administração). Depois, no cadastro de cada colaborador, escolha o **Gestor** dele.",
          "**Central do Ponto** (opcional, se houver tablet na empresa): Gestão > Cadastros > Centrais > **Cadastrar uma central** e faça o pareamento no tablet.",
          "**Crachás** (para quem usa a Central): Gestão > Cadastros > Pessoas > **Crachás de todos (PDF)**. Imprima e entregue.",
          "**Login**: entregue a cada pessoa o endereço do app e a senha inicial (ou peça que entre com o Google usando o e-mail cadastrado). Se quiser aceitar só o Google, veja Configurações > Login.",
          "**Teste**: peça a uma pessoa que registre o ponto e confira em Gestão > Painel.",
        ],
      },
      {
        warn: "O CNPJ não muda pela tela: ele identifica o estabelecimento nos registros oficiais do REP-P. Se precisar corrigir, fale com o suporte técnico.",
      },
    ],
  },
  {
    id: "entrar",
    group: "Comece por aqui",
    title: "Entrar, sair e esqueci a senha",
    who: "Todos",
    summary: "Entrar com Google ou com e-mail e senha, verificação em duas etapas, o que fazer se esquecer a senha e como sair.",
    blocks: [
      {
        h: "Entrar com o Google",
        steps: [
          "Na tela de entrada, toque em **Entrar com Google**.",
          "Escolha a conta Google. Ela precisa ter o **mesmo e-mail cadastrado** na empresa, ou ter sido vinculada antes em Minha conta.",
        ],
      },
      {
        h: "Entrar com e-mail e senha",
        steps: [
          "Toque em **Entrar com e-mail e senha** (aparece só se a empresa permitir senha).",
          "Digite o e-mail e a senha e toque em **Entrar**.",
          "Se a sua conta tem verificação em duas etapas, digite o código de 6 dígitos do aplicativo autenticador. Perdeu o celular? Use um dos **códigos de recuperação** no lugar do código.",
        ],
      },
      {
        h: "Esqueci a senha",
        text: "Não existe recuperação por e-mail. Peça ao RH ou à Administração: em Cadastros > Pessoas, eles abrem o seu cadastro e tocam em **Nova senha**. Você recebe uma senha temporária e cria a sua no primeiro acesso. Com a conta Google vinculada, você nem precisa de senha.",
      },
      {
        h: "Sair",
        text: "Minha conta (bolinha com as iniciais) > botão **Sair** no fim da tela. No celular, também em Mais > Sair. Em aparelho compartilhado, sempre saia ao terminar.",
      },
    ],
  },
  {
    id: "instalar",
    group: "Comece por aqui",
    title: "Instalar o aplicativo",
    who: "Todos",
    where: { path: "/mais", label: "Mais" },
    summary: "Colocar o Ponto na tela inicial do celular ou do computador, e o que fazer se a instalação não aparecer.",
    blocks: [
      {
        h: "Android (Chrome)",
        steps: [
          "Abra o app no Chrome e entre.",
          "Toque em **Mais** (barra de baixo) > **Instalar aplicativo**. Se o botão não aparecer, use o menu ⋮ do Chrome > **Instalar app** ou **Adicionar à tela inicial**.",
        ],
      },
      {
        h: "iPhone (Safari)",
        steps: [
          "Abra o app no **Safari** (no iPhone a instalação só funciona pelo Safari).",
          "Toque em **Compartilhar** (quadrado com seta) > **Adicionar à Tela de Início** > **Adicionar**.",
        ],
      },
      {
        h: "Computador (Chrome ou Edge)",
        text: "Clique no ícone de instalar que aparece na barra de endereço, ou no menu do navegador > Instalar.",
      },
      {
        h: "A instalação não aparece?",
        list: [
          "**Link aberto pelo WhatsApp, Instagram ou e-mail**: esses apps abrem o link num navegador interno, que não instala e não funciona sem internet. O Ponto avisa na tela de entrada: toque em **Abrir no Chrome** (Android) ou use o menu > **Abrir no Safari** (iPhone). É a causa mais comum.",
          "**iPhone**: instale pelo **Safari**. Em outros navegadores do iPhone, toque em **Copiar endereço** e cole no Safari.",
          "**Internet Samsung, Firefox, Mi Browser e outros**: se o menu não tiver Instalar, abra no **Chrome**.",
          "**Aba anônima**: não instala e apaga tudo ao fechar. Abra numa aba normal.",
          "**Pouco espaço no aparelho**: o app precisa guardar os arquivos dele. Libere espaço e abra de novo.",
          "**Celular muito antigo** (Android anterior ao 8 ou iOS anterior ao 16): atualize o Chrome ou o sistema; se não der, a pessoa bate o ponto na Central ou com internet.",
        ],
      },
      {
        text: "Abra Mais > **Diagnóstico do aplicativo**. A tela mostra o navegador detectado, como instalar nesse aparelho e, item por item, se o app consegue funcionar sem internet. Uma linha vermelha é o motivo.",
      },
      {
        h: "Funcionar sem internet",
        steps: [
          "Abra o app **com internet** e entre na sua conta pelo menos uma vez no aparelho.",
          "Recarregue a página uma vez (ou feche e abra o app). No Diagnóstico, **Aplicativo guardado para uso sem internet** deve ficar verde.",
          "Pronto: sem conexão, o app abre e guarda as batidas (veja **Registrar sem internet**).",
        ],
        tip: "Instalar não é obrigatório para funcionar sem internet no Android, mas ajuda: o aparelho protege os dados do app contra limpeza automática. No iPhone, use sempre pelo ícone da Tela de Início: o que fica guardado no Safari e no ícone são separados.",
      },
    ],
  },

  // ───────────────────────────── Meu ponto ─────────────────────────────
  {
    id: "registrar",
    group: "Meu ponto",
    title: "Registrar o ponto",
    who: "Quem registra ponto",
    need: ["punch"],
    where: { path: "/", label: "Ponto" },
    summary: "As quatro batidas do dia, sair sem intervalo, comprovante de cada batida, localização e foto.",
    blocks: [
      {
        h: "Passo a passo",
        steps: [
          "Abra a tela **Ponto** (primeira da área Meu ponto).",
          "Confira o relógio e a situação (ex.: Fora do expediente, Trabalhando, Em intervalo).",
          "Logo abaixo do botão aparece a **próxima batida** (ex.: 1ª · Entrada).",
          "Toque em **Registrar ponto**. Se a foto estiver ativa e autorizada, a câmera abre: olhe para ela e aguarde.",
          "A batida aparece na lista **Hoje** com o horário e o link **Comprovante**.",
        ],
      },
      {
        h: "A sequência do dia",
        list: [
          "1ª **Entrada** → 2ª **Intervalo** (saída para o almoço) → 3ª **Retorno do intervalo** → 4ª **Saída**.",
          "O app escolhe sozinho qual é a próxima: você só toca no botão.",
          "Depois da saída aparece **Jornada encerrada**: não há quinta batida no dia.",
          "Se for embora sem fazer o intervalo, depois da entrada toque em **Vou embora sem fazer o intervalo**: a batida vira Saída.",
        ],
      },
      {
        h: "Comprovante",
        text: "Cada batida gera um comprovante oficial em PDF, com o NSR (número sequencial do registro). Baixe pelo link **Comprovante** na lista Hoje ou, para dias anteriores, em Registros > Comprovantes das últimas batidas.",
      },
      {
        h: "Localização e foto",
        list: [
          "A localização é opcional e serve só para conferir a jornada. Você autoriza ou recusa no aviso da tela Ponto.",
          "A foto só existe se a empresa ativou. É opcional para você, fica criptografada, só o RH e a Administração veem e ela é apagada quando o mês é fechado.",
        ],
      },
      {
        h: "No computador",
        text: "Ao lado do botão aparecem o resumo da semana e, para gestores, quem da equipe está trabalhando.",
      },
      {
        tip: "Bateu errado ou esqueceu de bater? Não tente compensar batendo de novo: peça a correção em **Solicitações**.",
      },
    ],
  },
  {
    id: "sem-internet",
    group: "Meu ponto",
    title: "Registrar sem internet",
    who: "Quem registra ponto",
    need: ["punch"],
    where: { path: "/", label: "Ponto" },
    summary: "O que acontece quando a internet cai: a batida fica guardada no aparelho e é enviada depois.",
    blocks: [
      {
        steps: [
          "Sem conexão, o app mostra uma faixa avisando. Toque em **Registrar ponto** normalmente.",
          "Aparece o quadro **Guardado — aguardando envio**, com o horário e um protocolo. Ele **ainda não é o comprovante oficial**.",
          "Quando a internet voltar, o app envia sozinho (ao abrir o app e a cada 30 segundos). Você também pode tocar em **Enviar agora** no quadro **Aguardando envio**.",
          "Depois de enviada, a batida ganha NSR e comprovante, com o horário em que você realmente tocou no botão.",
        ],
      },
      {
        warn: "Conecte-se em até **72 horas**. Depois desse prazo a batida guardada não é mais aceita: peça a inclusão em Solicitações. Não limpe os dados do navegador nem desinstale o app com batidas aguardando envio.",
      },
      {
        text: "Se uma batida guardada for recusada, ela aparece em vermelho com o motivo. Ela não vale como registro: se você trabalhou nesse horário, peça a inclusão em **Solicitações** e toque em **Descartar** para limpar o aviso.",
      },
    ],
  },
  {
    id: "registros",
    group: "Meu ponto",
    title: "Registros: o espelho do mês",
    who: "Quem registra ponto",
    need: ["punch"],
    where: { path: "/registros", label: "Registros" },
    summary: "Ver as horas do mês, o saldo, as faltas e cada dia; baixar a folha de ponto e os comprovantes.",
    blocks: [
      {
        h: "O que a tela mostra",
        list: [
          "No topo, as setas **‹ ›** trocam o mês.",
          "**Trabalhadas**, **Previstas** e **Saldo** do mês (saldo positivo em verde, negativo em vermelho).",
          "Linha com **Faltas**, dias **Justificados** e dias **Incompletos** (com batida faltando).",
          "Lista de dias com a situação de cada um, as batidas e as horas. Toque num dia para ver os detalhes e os alertas.",
        ],
      },
      {
        h: "Filtros da lista",
        list: [
          "**Dias úteis**: só os dias com jornada prevista.",
          "**Pendências**: só os dias com falta, batida faltando ou alerta (o número ao lado diz quantos).",
          "**Todos**: o mês inteiro, inclusive folgas e feriados.",
        ],
      },
      {
        h: "Situações de um dia",
        list: [
          "**Completo**: as batidas fecham. **Falta**: dia útil sem nenhuma batida. **Incompleto**: falta uma batida (ex.: a saída).",
          "**Justificado**: atestado, abono, férias ou licença aprovados. **Feriado** e **Folga**: sem jornada prevista.",
          "**Alerta**: por exemplo, intervalo menor que 1 hora em jornada acima de 6 horas, ou mais de 2 horas extras no dia.",
        ],
      },
      {
        h: "Corrigir um dia",
        steps: ["Toque no dia.", "Toque em **Pedir correção deste dia**: abre Solicitações com a data já preenchida."],
      },
      {
        h: "Documentos",
        list: [
          "**Folha de ponto (PDF)**: uma página A4 com o mês, para conferir e assinar.",
          "**Espelho detalhado (com NSR)**: versão completa, com o número de cada registro.",
          "**Comprovantes das últimas batidas**: o PDF de cada batida, no fim da tela.",
        ],
      },
    ],
  },
  {
    id: "solicitacoes",
    group: "Meu ponto",
    title: "Solicitações: corrigir marcação, atestado e abono",
    who: "Quem registra ponto",
    need: ["punch"],
    where: { path: "/solicitacoes", label: "Solicitações" },
    summary: "Pedir a inclusão de uma batida esquecida, a exclusão de uma batida errada, enviar atestado ou pedir abono, e acompanhar a resposta.",
    blocks: [
      {
        h: "Esqueci de bater o ponto",
        steps: [
          "Em **Novo pedido**, escolha **Corrigir marcação** e depois **Esqueci de bater**.",
          "Informe a **Data**, a **Hora** e **Qual marcação** (Entrada, Intervalo, Retorno do intervalo ou Saída).",
          "Escreva a **Justificativa** ou toque numa das prontas (ex.: Esqueci de bater o ponto).",
          "Toque em **Enviar pedido**.",
        ],
      },
      {
        h: "Bati por engano",
        steps: [
          "Escolha **Corrigir marcação** > **Bati por engano**.",
          "Em **Qual marcação foi por engano?**, escolha a batida na lista.",
          "Escreva a justificativa e toque em **Enviar pedido**. A batida original nunca é apagada: se aprovada, ela passa a ser desconsiderada no cálculo.",
        ],
      },
      {
        h: "Atestado médico ou abono de falta",
        steps: [
          "Escolha **Atestado ou abono** e depois **Atestado médico** ou **Abono de falta**.",
          "Informe **De** e **Até**. Se for um dia só, escolha **Dia inteiro** ou **Parte do dia** (com as horas e os minutos).",
          "Em **Motivo**, explique brevemente. **Não informe diagnóstico nem CID.**",
          "Toque em **Enviar pedido** e entregue o documento original a quem cuida do pessoal na empresa.",
        ],
      },
      {
        h: "Acompanhar",
        list: [
          "Em **Meus pedidos**, cada pedido mostra a situação: **Pendente**, **Aprovado/Aprovada**, **Rejeitado/Rejeitada**, **Cancelada** ou **Desfeito**, e a resposta de quem decidiu.",
          "Atestados e abonos ainda pendentes podem ser cancelados em **Cancelar pedido** > **Confirmar cancelamento**.",
          "Quando a gestão corrige o seu ponto por conta própria (Tratamento), a correção também aparece aqui e no seu espelho.",
        ],
      },
      { tip: "Quem decide é o seu gestor; se você não tem gestor, o RH ou a Administração." },
    ],
  },
  {
    id: "meu-banco",
    group: "Meu ponto",
    title: "Meu banco de horas",
    who: "Quem usa banco de horas",
    need: ["punch"],
    where: { path: "/banco", label: "Banco de horas" },
    summary: "Saldo atual, de onde ele vem e o extrato por período.",
    blocks: [
      {
        list: [
          "**Saldo atual** e desde quando conta (o início do seu banco).",
          "**Automático**: o saldo vindo do ponto (horas a mais menos horas a menos). **Créditos** e **Compensado**: lançamentos feitos pelo RH (ex.: folga compensatória).",
          "**Extrato**: escolha **De** e **Até** para ver o movimento dia a dia, com o saldo corrente.",
          "**Como funciona**: o limite do saldo e o prazo para compensar definidos pela empresa. Faltas de dia inteiro não descontam do banco automaticamente.",
          "Alertas avisam saldo perto do limite ou horas perto de vencer.",
        ],
      },
      { text: "Se a tela diz que você não usa banco de horas, ele não foi ativado no seu cadastro. Fale com o RH." },
    ],
  },
  {
    id: "minha-conta",
    group: "Meu ponto",
    title: "Minha conta: senha, Google e verificação em duas etapas",
    who: "Todos",
    where: { path: "/conta", label: "Minha conta" },
    summary: "Trocar a senha, vincular ou desvincular a conta Google, ativar a verificação em duas etapas e sair.",
    blocks: [
      {
        h: "Abrir",
        text: "Toque na bolinha com as suas iniciais, no canto superior direito (no celular, também em Mais > Minha conta).",
      },
      {
        h: "Vincular a conta Google",
        steps: [
          "No quadro **Como você entra**, toque em **Continuar com o Google**.",
          "Escolha a conta. Pode ser uma conta com outro e-mail.",
          "A partir daí, entre com **Entrar com Google**. Para desfazer: **Desvincular a conta Google** > **Confirmar: desvincular** (só se a empresa permitir senha).",
        ],
      },
      {
        h: "Trocar a senha",
        steps: [
          "Abra **Trocar a senha**.",
          "Digite a **Senha atual**, a **Senha nova** e repita.",
          "Toque em **Trocar senha**. Regras: mínimo de 10 caracteres, letras e números, sem o e-mail nem o CPF.",
        ],
      },
      {
        h: "Verificação em duas etapas (2FA)",
        steps: [
          "Instale no celular um aplicativo autenticador (Google Authenticator, Microsoft Authenticator, Authy…).",
          "Em **Verificação em duas etapas**, toque em **Ativar** e escaneie o QR Code com o autenticador (ou digite a chave mostrada).",
          "Digite o código de 6 dígitos e toque em **Confirmar e ativar**.",
          "Guarde os **códigos de recuperação** (Baixar ou Copiar) e toque em **Já guardei**. Cada código vale uma vez, caso você perca o celular.",
          "Para gerar novos códigos ou desativar, use os botões do mesmo quadro (pedem a senha e um código).",
        ],
      },
      {
        text: "As opções de senha e 2FA só aparecem se a empresa permite entrar com senha. Quem bate ponto vê aqui também o quadro **Central do Ponto** (veja o tópico do crachá).",
      },
    ],
  },
  {
    id: "cracha",
    group: "Meu ponto",
    title: "Crachá, código interno e PIN (para a Central)",
    who: "Quem registra ponto",
    need: ["punch"],
    where: { path: "/conta", label: "Minha conta" },
    summary: "Como se identificar na Central do Ponto: QR do crachá ou do celular, código interno, CPF e PIN.",
    blocks: [
      {
        list: [
          "Em **Minha conta > Central do Ponto** ficam o seu **Código interno** (toque em **Mostrar**) e se o seu **PIN** está definido.",
          "**Meu crachá (QR)** mostra um QR Code que muda a cada 30 segundos. Na Central, mostre-o para a câmera: é o jeito mais rápido e dispensa o PIN.",
          "O crachá impresso (entregue pelo RH) tem o QR fixo e o código.",
          "Trate o código como uma senha: com ele a Central identifica você.",
        ],
      },
      {
        h: "Definir ou trocar o PIN",
        steps: [
          "Toque em **Definir PIN** (ou **Trocar o PIN**).",
          "Digite um PIN de 4 a 6 números, sem sequências óbvias (1234, 0000), e repita.",
          "Confirme com a sua senha atual. Se você entrou pelo Google, a troca só é aceita nos primeiros 15 minutos depois de entrar (por segurança).",
          "Toque em **Salvar PIN**.",
        ],
      },
      { text: "Esqueceu o PIN? O RH zera em Cadastros > Pessoas > **Zerar PIN**, e você define um novo." },
    ],
  },

  // ───────────────────────────── Gestão do dia a dia ─────────────────────────────
  {
    id: "painel",
    group: "Gestão do dia a dia",
    title: "Painel: indicadores do mês e quem está trabalhando",
    who: "Gestor, RH e Administração",
    need: ["team.view"],
    where: { path: "/gestao", label: "Painel" },
    summary: "Os números do mês, a situação de cada dia, o ranking por pessoa e a situação de agora.",
    blocks: [
      { text: "O gestor vê a própria equipe; o RH e a Administração veem a empresa toda. Quem não registra ponto não entra nos números." },
      {
        h: "Indicadores do mês",
        list: [
          "Use **‹ ›** para trocar o mês. A etiqueta **Fechado** indica mês já fechado.",
          "**Horas trabalhadas** (e previstas até hoje), **Horas extras** (e débitos), **Faltas**, **Atrasos** (dias com entrada depois da tolerância de 5 minutos), **A tratar** (dias com saída não registrada), **Aprovações** pendentes e **Banco de horas**.",
          "Os quadros em vermelho pedem ação. Toque em **Faltas** ou **A tratar** para ir ao Tratamento, e em **Aprovações** para decidir os pedidos.",
        ],
      },
      {
        h: "Situação dos dias",
        text: "Gráfico com quantas pessoas tiveram, em cada dia, o dia completo (verde), a saída não registrada (amarelo) ou falta (vermelho). Passe o mouse ou toque numa barra para ver os números; **Ver em tabela** mostra tudo em texto. Folgas, feriados e dias futuros ficam em branco.",
      },
      {
        h: "Por pessoa",
        text: "Escolha **Saldo**, **Faltas** ou **Atrasos** para ordenar. Toque numa pessoa para abrir o Tratamento dela no mesmo mês.",
      },
      {
        h: "Agora",
        list: [
          "Quem está **Trabalhando**, **Em intervalo**, **Saiu**, **Ainda não iniciou**, **Sem marcação** (deveria ter entrado e não entrou), **Saída não registrada**, **Ausência justificada** ou de **Folga**.",
          "Toque numa situação para filtrar a lista. Toque numa pessoa para abrir o espelho dela.",
          "A lista se atualiza sozinha a cada minuto. Em **Ver a situação em outro momento**, escolha data e hora para ver como estava.",
        ],
      },
    ],
  },
  {
    id: "aprovacoes",
    group: "Gestão do dia a dia",
    title: "Aprovações",
    who: "Gestor, RH e Administração",
    need: ["approvals"],
    where: { path: "/gestao/aprovacoes", label: "Aprovações" },
    summary: "Decidir os pedidos de correção de marcação, atestados e abonos.",
    blocks: [
      {
        steps: [
          "Abra Gestão > **Aprovações**. Cada pedido mostra quem pediu, o que pede e a justificativa.",
          "Para aprovar, toque em **Aprovar**.",
          "Para rejeitar, toque em **Rejeitar**, escreva o motivo (opcional, mas recomendado: a pessoa vê) e toque em **Confirmar rejeição**.",
          "O pedido sai da lista e a pessoa vê a decisão em Solicitações. O espelho já considera o que foi aprovado.",
        ],
      },
      {
        h: "Quem decide o quê",
        list: [
          "O **gestor** decide os pedidos da própria equipe.",
          "O **RH** e a **Administração** decidem os de qualquer pessoa.",
          "Ninguém decide o próprio pedido, com uma exceção: se **ninguém mais** na empresa pode decidir, a Administração decide o seu, escrevendo uma **justificativa obrigatória** (mínimo de 10 caracteres), que fica em destaque na auditoria.",
        ],
      },
      { tip: "Pedidos pendentes impedem o fechamento do mês. Decida tudo antes de fechar." },
    ],
  },
  {
    id: "espelhos",
    group: "Gestão do dia a dia",
    title: "Espelhos e folhas de ponto",
    who: "Gestor, RH e Administração",
    need: ["team.view"],
    where: { path: "/gestao/espelhos", label: "Espelhos" },
    summary: "Ver o mês de cada pessoa, gerar a folha de ponto individual ou de todos de uma vez, e ver as fotos das batidas.",
    blocks: [
      {
        steps: [
          "Abra Gestão > **Espelhos** e escolha o **Colaborador** e o mês (setas ‹ ›).",
          "A tela é igual à de Registros da pessoa: totais, filtros (Dias úteis, Pendências, Todos) e os dias.",
          "**Folha de ponto (PDF)**: a folha mensal em uma página A4, com espaço para as assinaturas do empregado e do empregador.",
          "**Espelho detalhado (com NSR)**: a versão completa, com o número de cada registro.",
          "**Corrigir este mês em Tratamento →** leva direto ao Tratamento da pessoa.",
        ],
      },
      {
        h: "Folhas de todos de uma vez",
        text: "Toque em **Folhas de ponto de todos de [mês]**: sai um único PDF, uma página por pessoa em ordem alfabética, pronto para imprimir e colher as assinaturas. Entram as pessoas ativas que registram ponto e quem foi desativado mas teve marcações no mês. O gestor recebe só a equipe dele.",
      },
      {
        h: "Fotos das batidas (RH e Administração)",
        text: "Se a empresa usa foto, o quadro **Fotos das batidas** lista as fotos do mês; toque em **Ver foto**. Cada consulta fica na auditoria, e as fotos são apagadas quando o mês é fechado.",
      },
    ],
  },
  {
    id: "tratamento",
    group: "Gestão do dia a dia",
    title: "Tratamento: corrigir o ponto do mês",
    who: "Gestor, RH e Administração",
    need: ["approvals"],
    where: { path: "/gestao/tratamento", label: "Tratamento" },
    summary: "Corrigir o mês de uma pessoa por conta própria: incluir batida esquecida, desconsiderar batida errada, justificar o dia e desfazer.",
    blocks: [
      {
        text: "A batida original nunca é apagada. Cada correção fica com o motivo e o autor, aparece no espelho e nas Solicitações da pessoa, entra no AEJ e fica na auditoria.",
      },
      {
        h: "Abrir",
        steps: [
          "Gestão > **Tratamento**. Escolha o **Colaborador** e o mês.",
          "Por padrão aparecem os **Dias úteis**. Toque em **Pendências** para ver só os dias com falta, batida faltando ou alerta (o caminho mais rápido), ou em **Todos** para o mês inteiro.",
          "Toque num dia para abrir as batidas dele.",
        ],
      },
      {
        h: "Incluir uma batida esquecida",
        steps: [
          "No dia, toque em **Incluir marcação**.",
          "Escolha a **Marcação** (Entrada, Intervalo, Retorno do intervalo ou Saída) e a **Hora**.",
          "Escolha um motivo pronto (Esqueceu de bater, Trabalho externo, Falha no aparelho, Sem internet no momento) ou escreva o seu.",
          "Toque em **Incluir**.",
        ],
      },
      {
        h: "Desconsiderar uma batida errada",
        steps: [
          "Na batida, toque em **Desconsiderar**.",
          "Escolha o motivo (Batida duplicada, Batida por engano, Batida fora do horário real) ou escreva.",
          "Toque em **Desconsiderar** para confirmar. A batida continua visível, riscada, com o motivo e o autor.",
        ],
      },
      {
        h: "Justificar o dia (RH e Administração)",
        steps: [
          "No dia, toque em **Justificar o dia**.",
          "Escolha o **Tipo** (Abono, Atestado médico, Férias, Licença, Afastamento INSS). Para justificar só parte do dia, marque a opção e informe as horas.",
          "Escreva o **Motivo** (sem diagnóstico nem CID) e toque em **Justificar**.",
          "Para vários dias seguidos (férias, licença), use Gestão > Ausências.",
        ],
      },
      {
        h: "Desfazer",
        text: "Ao lado de cada batida incluída ou desconsiderada aparece o link **Desfazer**: a inclusão sai do cálculo, ou a batida desconsiderada volta a valer. A correção fica registrada como desfeita. Só é possível enquanto o mês estiver aberto.",
      },
      {
        h: "Pedidos pendentes",
        text: "Se a pessoa já pediu correção para aquele dia, o pedido aparece em destaque com o link **Decidir em Aprovações**.",
      },
      {
        warn: "Mês fechado não aceita correções: reabra em Empresa > Fechamento. Uma correção da gestão não é decidida por ninguém: ela já entra aprovada.",
      },
    ],
  },
  {
    id: "inconsistencias",
    group: "Gestão do dia a dia",
    title: "Inconsistências: o que a CLT pede atenção",
    who: "Gestor, RH, Administração e Auditoria",
    need: ["team.view"],
    where: { path: "/gestao/inconsistencias", label: "Inconsistências" },
    summary: "Lista do mês com faltas, saídas não registradas, intervalo curto, menos de 11 h entre jornadas, 7º dia sem folga, horas extras demais e ponto britânico.",
    blocks: [
      {
        text: "O aplicativo confere o espelho de cada pessoa (com as correções e ausências já aprovadas) e aponta os dias que merecem atenção antes do fechamento. Nada é gravado no ponto: a lista é recalculada a cada consulta.",
      },
      {
        h: "O que é apontado",
        list: [
          "**Falta**: dia de trabalho previsto sem marcação nem justificativa.",
          "**Saída não registrada**: uma entrada ficou sem a saída.",
          "**Intervalo insuficiente** (CLT art. 71): menos de 1 h de intervalo em jornada acima de 6 h, ou menos de 15 min em jornada acima de 4 h.",
          "**Mais de 6 h sem intervalo** (art. 71): um trecho seguido de trabalho acima de 6 h, mesmo com intervalo em outro momento.",
          "**Mais de 2 h extras no dia** (art. 59): só em dias de trabalho previsto.",
          "**Menos de 11 h entre jornadas** (art. 66): da última saída até a primeira entrada seguinte.",
          "**7º dia seguido sem folga** (art. 67): a partir do 7º dia seguido com marcação.",
          "**Ponto britânico** (Súmula 338 do TST): 5 dias seguidos com exatamente os mesmos horários, o que tira a credibilidade do controle. Aparece uma vez por sequência, no primeiro dia dela.",
        ],
      },
      {
        h: "Tratar",
        steps: [
          "Gestão > **Inconsistências**. Escolha o mês; filtre por pessoa ou toque num tipo para ver só ele.",
          "Para corrigir o ponto, toque em **Abrir no tratamento**: o dia já abre na tela de Tratamento.",
          "Quando não há o que corrigir (ex.: hora extra autorizada), toque em **Marcar como resolvida**, escolha ou escreva a observação e confirme. Ela some da lista.",
          "Para ver de novo, marque **Mostrar as resolvidas**; **Reabrir** devolve a inconsistência para a lista.",
          "**Baixar planilha (CSV)** exporta o que está na tela, para abrir no Excel.",
        ],
      },
      {
        tip: "Se o ponto for corrigido depois, a inconsistência some sozinha. Marcar como resolvida não muda o cálculo: só registra que a gestão viu e tratou (fica na auditoria).",
      },
      {
        warn: "O gestor vê e resolve só a própria equipe; ninguém resolve as próprias inconsistências. A Auditoria só consulta.",
      },
    ],
  },
  {
    id: "banco-equipe",
    group: "Gestão do dia a dia",
    title: "Banco de horas da equipe",
    who: "Gestor, RH e Administração",
    need: ["team.view"],
    where: { path: "/gestao/banco", label: "Banco de horas" },
    summary: "Saldos de quem usa banco de horas, o extrato de cada um e os lançamentos de crédito e compensação.",
    blocks: [
      {
        steps: [
          "Gestão > **Banco de horas** lista quem usa banco, com o saldo e os alertas (saldo perto do limite, horas perto de vencer).",
          "Toque numa pessoa para ver o saldo detalhado e o **Extrato** (escolha De e Até).",
        ],
      },
      {
        h: "Fazer um lançamento (RH e Administração)",
        steps: [
          "Na pessoa, abra **Fazer um lançamento**.",
          "Escolha **Compensação (−)** para descontar horas (ex.: folga compensatória) ou **Crédito (+)** para somar.",
          "Informe as horas, os minutos, a **Data** e o **Motivo** (ex.: folga compensatória de 12/08).",
          "Toque em **Lançar**.",
        ],
      },
      {
        list: [
          "Lançamentos não se editam nem se apagam: para corrigir, faça o lançamento contrário.",
          "A compensação não pode passar do saldo, e não se lança em mês fechado.",
          "Quem usa banco de horas é definido no cadastro de cada pessoa; as regras (limite e prazo) ficam em Empresa > Configurações.",
        ],
      },
    ],
  },
  {
    id: "ausencias",
    group: "Gestão do dia a dia",
    title: "Ausências: férias, licenças, atestados e afastamentos",
    who: "Gestor, RH e Administração",
    need: ["team.view"],
    where: { path: "/gestao/ausencias", label: "Ausências" },
    summary: "Ver as ausências da equipe ou da empresa, registrar férias, licenças e afastamentos em nome de alguém e lançar abono ou férias coletivas para várias pessoas.",
    blocks: [
      {
        h: "Registrar (RH e Administração)",
        steps: [
          "Gestão > **Ausências** > **Registrar ausência de um colaborador**.",
          "Escolha o **Colaborador** e o **Tipo**: Atestado médico, Abono de falta, Férias, Licença ou Afastamento INSS.",
          "Informe **De** e **Até** (para um dia só, pode escolher Parte do dia em atestado e abono).",
          "Escreva o **Motivo** (sem diagnóstico nem CID) e toque em **Registrar**. A ausência registrada pelo RH já entra aprovada.",
        ],
      },
      {
        h: "Para várias pessoas de uma vez (em lote)",
        steps: [
          "Gestão > **Ausências** > **Lançar para várias pessoas (em lote)**. Serve para ponte de feriado, recesso, queda de energia ou férias coletivas.",
          "Escolha **Abono** ou **Férias coletivas**, o período (**De** e **Até**) e, no abono de um dia só, se é o **Dia inteiro** ou **Parte do dia**.",
          "Escolha um motivo pronto ou escreva o seu.",
          "Marque as pessoas: uma a uma, **Todas** ou por cargo (**+ cargo**). A busca pelo nome ajuda em equipes grandes.",
          "Toque em **Conferir**. Nada é gravado ainda: aparece quantas pessoas recebem e quem fica de fora, com o motivo (ex.: já tem atestado no período).",
          "Toque em **Lançar**. Cada pessoa recebe a ausência já aprovada; no espelho o dia aparece como Justificado.",
        ],
      },
      {
        text: "Em **Lotes lançados** fica cada lote, com quem lançou e para quem. **Cancelar lote** desfaz o lote inteiro de uma vez (enquanto o mês estiver aberto); para tirar uma pessoa só, cancele a ausência dela na lista abaixo.",
      },
      {
        list: [
          "A lista mostra as ausências com a situação. Pedidos pendentes têm o atalho **Abrir Aprovações**.",
          "Para cancelar uma ausência, toque em **Cancelar** > **Confirmar cancelamento**.",
          "Nos dias justificados ninguém leva falta: o dia aparece como Justificado no espelho.",
        ],
      },
    ],
  },
  {
    id: "relatorios",
    group: "Gestão do dia a dia",
    title: "Relatórios",
    who: "Gestor, RH e Administração",
    need: ["team.view"],
    where: { path: "/gestao/relatorios", label: "Relatórios" },
    summary: "Fechamento mensal, banco de horas, ausências, batidas por origem e divergências da Central, em PDF ou CSV.",
    blocks: [
      {
        list: [
          "**Fechamento mensal**: escolha o mês. Horas trabalhadas, saldo, faltas, dias justificados e banco de horas de cada pessoa.",
          "**Banco de horas**: a posição de hoje (saldo, limite e horas em risco de vencer).",
          "**Ausências justificadas**: período e situação (todas, aprovadas, pendentes, rejeitadas, canceladas). Motivos de saúde só aparecem para o RH.",
          "**Batidas por origem**: cada marcação do período, com a origem (aplicativo ou Central) e a distância ao posto.",
          "**Divergências da Central** (RH e Administração): batidas fora do posto ou sem localização, falhas de identificação e aparelhos sem sinal.",
        ],
      },
      { text: "Cada relatório tem os botões **Baixar PDF** (para ler ou imprimir) e **Baixar planilha (CSV)** (para abrir no Excel). O gestor recebe só a equipe dele. Cada emissão fica na auditoria. O documento oficial de cada pessoa continua sendo a folha ou o espelho de ponto." },
    ],
  },
  {
    id: "rotina-mensal",
    group: "Gestão do dia a dia",
    title: "Rotina do fim do mês",
    who: "RH e Administração",
    need: ["closing.manage"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "O roteiro para fechar o mês sem pendências e colher as assinaturas.",
    blocks: [
      {
        steps: [
          "No **Painel**, veja os quadros **Faltas**, **A tratar** e **Aprovações** do mês.",
          "Em **Aprovações**, decida todos os pedidos pendentes (o fechamento exige zero pendências).",
          "Em **Tratamento**, passe pessoa por pessoa na visão **Pendências**: inclua as batidas esquecidas, desconsidere as erradas e justifique as faltas que tiverem documento.",
          "Em **Inconsistências**, zere a lista do mês: corrija no Tratamento ou marque como resolvida (hora extra autorizada, por exemplo).",
          "Em **Ausências**, confira férias, licenças e atestados do mês.",
          "Em **Espelhos**, gere **Folhas de ponto de todos** e colha a assinatura de cada pessoa (e do empregador).",
          "Em **Relatórios**, baixe o **Fechamento mensal** para a folha de pagamento.",
          "Em **Empresa > Fechamento**, escolha o mês e toque em **Fechar**.",
        ],
      },
      { tip: "Faça o Tratamento ao longo do mês (por exemplo, toda semana): o fechamento fica rápido." },
    ],
  },

  // ───────────────────────────── Cadastros ─────────────────────────────
  {
    id: "pessoas",
    group: "Cadastros",
    title: "Pessoas: cadastrar, editar, desativar e excluir",
    who: "RH e Administração",
    need: ["people.manage"],
    where: { path: "/gestao/cadastros", label: "Cadastros" },
    summary: "O cadastro de cada pessoa, campo por campo, e as ações da ficha: crachá, PIN, senha, 2FA, desativar e excluir.",
    blocks: [
      {
        h: "Cadastrar uma pessoa",
        steps: [
          "Gestão > **Cadastros** > aba **Pessoas** > **Cadastrar uma pessoa**.",
          "**Dados**: Nome, CPF e Cargo ou função.",
          "**Ponto**: deixe **Registra ponto** marcado para quem bate ponto (desmarque para quem só faz gestão). Informe a **Data de admissão** (dias antes dela não geram falta), a **Jornada**, o **Gestor** (se nenhum, o RH ou a Administração aprovam os pedidos), **Onde bate o ponto** (Aplicativo e Central, ou Só na Central) e se **Usa banco de horas**.",
          "**Acesso**: deixe **Entra no aplicativo** marcado e informe o **E-mail** e uma **Senha inicial** (mínimo de 8 caracteres; é temporária e a pessoa cria a dela no primeiro acesso). Desmarque para quem só bate ponto na Central: não precisa de e-mail nem senha.",
          "**Funções de gestão** (só a Administração vê): marque Administração, RH e/ou Gestor, quantas quiser.",
          "Toque em **Cadastrar**.",
        ],
      },
      {
        h: "Encontrar e editar",
        list: [
          "Use o campo **Buscar por nome ou e-mail**. **Mostrar inativos** inclui quem foi desativado.",
          "Toque na pessoa para abrir a ficha e em **Editar cadastro** para mudar os dados. Salvar envia só o que mudou.",
          "O CPF só pode ser corrigido enquanto a pessoa não tem marcações. Trocar a jornada muda o cálculo dos meses abertos e é recusado se houver mês fechado com marcações dela.",
          "Só a Administração altera quem tem função de gestão.",
        ],
      },
      {
        h: "Ações da ficha",
        list: [
          "**Crachá (PDF)**: o crachá da pessoa, para imprimir. **Crachás de todos (PDF)**, no topo da lista, gera todos de uma vez.",
          "**Regenerar crachá**: o QR do crachá impresso deixa de funcionar na Central (use se o crachá foi perdido); imprima o novo.",
          "**Zerar PIN**: apaga o PIN da Central; a pessoa define outro em Minha conta.",
          "**Nova senha**: gera uma senha temporária, que aparece só naquele momento (Copiar). A pessoa troca no primeiro acesso.",
          "**Zerar 2FA**: desliga a verificação em duas etapas de quem perdeu o celular e os códigos.",
          "**Desativar**: a pessoa deixa de entrar e de bater ponto, mas todo o histórico fica. É o caminho certo para desligamentos. **Reativar** desfaz.",
          "**Excluir**: só para cadastros feitos por engano, sem marcações nem outros registros. Se não der, use Desativar.",
        ],
      },
      { warn: "Você não pode desativar nem excluir o seu próprio cadastro. Para excluir um gestor, troque antes o gestor das pessoas da equipe dele." },
    ],
  },
  {
    id: "importar",
    group: "Cadastros",
    title: "Importar várias pessoas por planilha (CSV)",
    who: "RH e Administração",
    need: ["people.manage"],
    where: { path: "/gestao/cadastros", label: "Cadastros" },
    summary: "Cadastrar até 200 pessoas de uma vez a partir de uma planilha do Excel salva em CSV.",
    blocks: [
      {
        steps: [
          "Gestão > Cadastros > Pessoas > **Importar várias pessoas por CSV** > **Baixar modelo**.",
          "Preencha uma linha por pessoa. Obrigatórias: **nome**, **email**, **cpf**. Opcionais: **cargo**, **gestor** (o e-mail do gestor), **jornada** (o nome exato da jornada), **perfil**, **admissao** (dd/mm/aaaa) e **codigo** (código interno da Central, de 4 a 10 números; se vazio, é gerado).",
          "No Excel, salve como **CSV (separado por ponto e vírgula)**. Linhas vazias no fim são ignoradas.",
          "Escolha o arquivo e toque em **Validar arquivo**. Nada é gravado ainda: a tela lista os erros por linha e campo.",
          "Corrija os erros no Excel, escolha o arquivo de novo, valide e toque em **Importar**. A importação grava tudo ou nada.",
          "Toque em **Baixar senhas (.csv)** para guardar as senhas temporárias de cada pessoa. Elas aparecem só agora.",
        ],
      },
      { warn: "A planilha tem CPFs: guarde-a em local seguro e apague as cópias depois de importar. Entregue a cada pessoa somente a senha dela." },
    ],
  },
  {
    id: "importar-marcacoes",
    group: "Cadastros",
    title: "Importar marcações de outro sistema de ponto",
    who: "RH e Administração",
    need: ["closing.manage"],
    where: { path: "/gestao/cadastros", label: "Cadastros" },
    summary: "Trazer as batidas de um período em que a empresa ainda usava outro sistema, por planilha CSV.",
    blocks: [
      {
        text: "As batidas entram como **inclusões aprovadas** (tratamento), com o motivo que você escrever. Elas aparecem tratadas no Espelho e na folha e vão para o AEJ. Pela Portaria 671, uma batida feita em outro relógio não vira marcação original deste ponto: **guarde o AFD e os relatórios do sistema anterior**, que continuam sendo os registros originais desses dias.",
      },
      {
        h: "A planilha",
        list: [
          "Uma linha por pessoa e dia, separada por ponto e vírgula (Excel em CSV serve).",
          "Colunas obrigatórias: **cpf**, **data** (dd/mm/aaaa) e **batida_1**, **batida_2**, **batida_3**, **batida_4** (HH:MM). Também vale uma coluna **batidas** com os horários separados por espaço.",
          "Outras colunas (nome, ocorrência, totais) são ignoradas. Linhas sem batidas (folga, feriado, férias) também.",
          "A ordem define o tipo: 1ª entrada, 2ª intervalo, 3ª retorno, 4ª saída. Com 2 batidas: entrada e saída.",
        ],
      },
      {
        h: "Importar",
        steps: [
          "Gestão > Cadastros > aba **Pessoas** > **Importar marcações de outro sistema de ponto (CSV)**.",
          "Confira o **Motivo** (ex.: Migração do sistema de ponto anterior). Ele vai em cada inclusão e na auditoria.",
          "Escolha o arquivo e toque em **Validar arquivo**. Nada é gravado: a tela mostra quantas marcações entram por pessoa, os problemas, os avisos e os dias que ficam de fora.",
          "Corrija no Excel as linhas com problema e valide de novo. A importação grava tudo ou nada.",
          "Toque em **Importar N marcações**. Depois confira o Espelho de algumas pessoas em Gestão > Tratamento.",
        ],
      },
      {
        list: [
          "**Dias que já têm marcações no app ficam de fora**, para não duplicar. Importar o mesmo arquivo duas vezes não duplica nada.",
          "Pessoas são encontradas pelo **CPF**: cadastre todas antes. O mês não pode estar fechado.",
          "Férias e atestados se lançam em **Ausências**; o saldo do banco de horas anterior, em **Banco de horas** (lançamento manual).",
          "Errou? Em **Importações feitas**, toque em **Desfazer importação** > **Confirmar**: todas as inclusões daquela importação deixam de valer, com a trilha na auditoria.",
        ],
      },
      { warn: "A planilha tem CPFs e horários de trabalho: guarde-a em local seguro e apague as cópias depois de importar." },
    ],
  },
  {
    id: "jornadas",
    group: "Cadastros",
    title: "Jornadas de trabalho",
    who: "RH e Administração",
    need: ["schedules.manage"],
    where: { path: "/gestao/cadastros", label: "Cadastros" },
    summary: "Criar e ajustar os horários: dias de trabalho, carga diária, intervalo, tolerância e horários de referência.",
    blocks: [
      {
        h: "Criar",
        steps: [
          "Gestão > Cadastros > aba **Jornadas** > **Criar uma jornada**.",
          "**Nome** (ex.: Comercial 8h).",
          "**Dias de trabalho**: toque nos dias para marcar e desmarcar.",
          "**Carga diária (h)**: horas a trabalhar por dia (ex.: 8 ou 7,33).",
          "Se quiser, toque num **modelo** em Começar de um modelo (Integral 8 h, 6 h ou **Meio período 4 h, sem intervalo**): ele preenche os campos e você só ajusta.",
          "**Intervalo (min; 0 = sem intervalo)**: duração do almoço (ex.: 60). Com **0**, o campo Início do intervalo some e o ponto do dia passa a ter só entrada e saída.",
          "**Tolerância** (máximo de 10 minutos por dia): diferenças até esse limite não viram saldo.",
          "**Primeira entrada** e **Início do intervalo**: os horários de referência (usados para atraso e para a folha de ponto).",
          "Para turnos noturnos, marque a opção de a jornada virar a meia-noite (terminar no dia seguinte). Ela também pode ser ligada depois, na lista de jornadas.",
          "Toque em **Criar jornada**. Depois, escolha a jornada no cadastro de cada pessoa.",
        ],
      },
      {
        h: "Meio período e estágio (4 h sem intervalo)",
        steps: [
          "Em **Criar uma jornada**, toque no modelo **Meio período 4 h, sem intervalo** (ou preencha Carga diária **4** e Intervalo **0**).",
          "Ajuste o **Nome** (ex.: Estágio manhã), os **Dias de trabalho** e a **Primeira entrada** (ex.: 08:00 para a manhã, 13:00 para a tarde).",
          "Toque em **Criar jornada** e escolha essa jornada no cadastro de cada estagiário.",
        ],
        tip: "Até 4 h por dia a lei não exige intervalo. De 4 h a 6 h, são 15 min; acima de 6 h, 1 h (CLT art. 71). O formulário avisa quando o intervalo fica abaixo disso. Para estágio, a Lei 11.788 limita a 6 h por dia e 30 h por semana.",
      },
      {
        h: "Editar e excluir",
        list: [
          "**Editar** muda a jornada. Só o nome muda sem afetar o cálculo; as demais mudanças valem para os dias ainda abertos e são recusadas se houver mês fechado com marcações de pessoas desta jornada.",
          "**Excluir** só funciona se nenhuma pessoa usa a jornada.",
        ],
      },
    ],
  },
  {
    id: "centrais",
    group: "Cadastros",
    title: "Centrais do Ponto: cadastrar e parear o tablet",
    who: "Administração",
    need: ["kiosks.view"],
    where: { path: "/gestao/cadastros", label: "Cadastros" },
    summary: "Cadastrar um tablet como relógio de ponto da empresa, parear, editar o posto, gerar novo código e revogar.",
    blocks: [
      {
        h: "Cadastrar e parear",
        steps: [
          "Gestão > Cadastros > aba **Centrais** > **Cadastrar uma central**.",
          "**Nome do aparelho** (ex.: CT-01 Recepção).",
          "**Posto**: latitude e longitude de onde o tablet fica. Estando no local, toque em **Usar minha localização atual**.",
          "**Raio de tolerância (metros)**: batidas fora desse raio não são bloqueadas, só ficam sinalizadas para conferência.",
          "Toque em **Cadastrar e gerar código de pareamento**. O código aparece só agora e vale por 15 minutos, uma única vez.",
          "No tablet, abra o endereço do app seguido de **/central** (a tela mostra o endereço exato), digite o código e toque em **Parear**.",
        ],
      },
      {
        h: "Manter",
        list: [
          "**Editar**: muda o nome, o posto e o raio.",
          "**Novo código de pareamento**: para trocar de tablet. O aparelho atual perde o acesso até ser pareado de novo.",
          "**Revogar**: o aparelho para de funcionar na hora (ex.: tablet roubado). As batidas já feitas continuam valendo.",
          "**Excluir** (só centrais revogadas): tira da lista; as batidas feitas nela continuam nos registros.",
          "O aviso **não dá sinal há mais de 1 hora** indica tablet desligado ou sem internet.",
          "São até 5 centrais ativas por empresa. Só a Administração cadastra e revoga; o RH vê a lista.",
        ],
      },
    ],
  },

  // ───────────────────────────── Empresa ─────────────────────────────
  {
    id: "configuracoes",
    group: "Empresa",
    title: "Configurações da empresa",
    who: "Administração",
    need: ["company.settings"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "Dados da empresa, feriados, regras do banco de horas, foto na batida, forma de login e PIN da Central.",
    blocks: [
      { text: "Gestão > **Empresa** > aba **Configurações**. Cada quadro salva separado." },
      {
        list: [
          "**Empresa**: razão social, local de prestação do serviço, CAEPF, CNO e fuso horário. O CNPJ aparece mas não muda por aqui. Mudanças nos dados do empregador ficam registradas no REP-P e na auditoria.",
          "**Feriados**: veja o tópico próprio.",
          "**Banco de horas**: **Limite do saldo** (em horas; vazio = sem limite) e **Prazo para compensar** (meses). O prazo depende do acordo adotado (individual ou coletivo); confirme com a assessoria jurídica.",
          "**Foto na batida**: liga ou desliga a foto pelo aplicativo. Cada pessoa autoriza a própria foto; as fotos são apagadas quando o mês é fechado. Na Central a foto é sempre obrigatória.",
          "**Login**: **Permitir também entrar com e-mail e senha**. Desmarcado, só se entra com o Google. Para desmarcar, vincule antes a sua própria conta Google em Minha conta.",
          "**Central do Ponto**: **Exigir PIN na Central**. Desligado, o código ou o CPF sozinho identifica a pessoa; ligado, ela também digita o PIN. O QR do aplicativo dispensa o PIN.",
        ],
      },
    ],
  },
  {
    id: "feriados",
    group: "Empresa",
    title: "Feriados",
    who: "Administração",
    need: ["company.settings"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "Feriados nacionais automáticos, Carnaval e Corpus Christi opcionais, e o cadastro dos estaduais e municipais.",
    blocks: [
      {
        list: [
          "Os **feriados nacionais** já estão incluídos e são calculados a cada ano, inclusive a Sexta-feira Santa e o 20 de novembro.",
          "**Folgar no Carnaval** e **Folgar em Corpus Christi**: marque se a empresa folga nesses pontos facultativos.",
          "Use **‹ ›** para ver a lista de outro ano. Cada feriado mostra a origem: Nacional, Facultativo ou Da empresa.",
          "Num feriado ninguém leva falta, e o que for trabalhado conta como hora extra.",
        ],
      },
      {
        h: "Cadastrar estadual ou municipal",
        steps: [
          "Gestão > Empresa > Configurações > Feriados > **Cadastrar feriado estadual ou municipal**.",
          "Use um atalho de Salvador/BA ou informe a **Data** e o **Nome**.",
          "Deixe **Repete todo ano nesta data** marcado para feriados fixos; desmarque para um feriado de um ano só.",
          "Toque em **Cadastrar**. Para tirar, toque em **Remover** ao lado do feriado.",
        ],
      },
      { warn: "Confirme as datas no calendário oficial do estado e da prefeitura. Feriados de um mês já fechado não podem ser incluídos nem removidos: reabra o mês antes." },
    ],
  },
  {
    id: "fechamento",
    group: "Empresa",
    title: "Fechamento do mês",
    who: "RH e Administração",
    need: ["closing.view"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "Fechar o mês para travar as alterações, e reabrir quando for preciso.",
    blocks: [
      {
        h: "Fechar",
        steps: [
          "Faça antes a rotina do fim do mês (veja o tópico próprio).",
          "Gestão > **Empresa** > aba **Fechamento**. Em **Fechar mês**, escolha o mês e toque em **Fechar**.",
        ],
      },
      {
        h: "O que o fechamento faz",
        list: [
          "Exige que não haja ajustes nem ausências pendentes no mês.",
          "Bloqueia novas correções, ausências, lançamentos de banco e mudanças de feriado e de jornada que afetem o mês.",
          "Apaga as fotos das batidas do mês.",
        ],
      },
      {
        h: "Reabrir",
        steps: ["Em **Meses fechados**, toque em **Reabrir** no mês e depois em **Confirmar reabertura**.", "Corrija o que precisar e feche de novo."],
      },
      { text: "Só o RH e a Administração fecham e reabrem. A reabertura fica na auditoria." },
    ],
  },
  {
    id: "fiscalizacao",
    group: "Empresa",
    title: "Fiscalização: AFD, AEJ e integridade",
    who: "RH e Administração",
    need: ["fiscal.export", "integrity.view"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "Os arquivos oficiais da Portaria 671 para o Auditor-Fiscal do Trabalho e a verificação de integridade das marcações.",
    blocks: [
      {
        steps: [
          "Gestão > **Empresa** > aba **Fiscalização**.",
          "Se aparecer **Pendências antes de emitir arquivos conformes**, resolva os itens listados (ou fale com o suporte técnico).",
          "Escolha o período (**De** e **Até**).",
          "Se houver certificado configurado, marque **Assinar com certificado ICP-Brasil** (baixa um .zip com o arquivo e a assinatura).",
          "Toque em **Baixar AFD** (todas as marcações, Anexo V) ou **Baixar AEJ** (a jornada tratada, Anexo VI).",
        ],
      },
      {
        h: "Integridade das marcações",
        text: "Toque em **Verificar agora**: o app confere se a numeração (NSR) é contínua e se a cadeia de segurança das marcações está intacta. Resultado verde = tudo certo.",
      },
      { tip: "Entregue os arquivos somente quando o Auditor-Fiscal pedir, e guarde uma cópia do que foi entregue." },
    ],
  },
  {
    id: "auditoria",
    group: "Empresa",
    title: "Auditoria",
    who: "Administração",
    need: ["audit.view"],
    where: { path: "/gestao/empresa", label: "Empresa" },
    summary: "O histórico de tudo o que foi feito no app: quem fez, o quê, quando e de onde.",
    blocks: [
      {
        list: [
          "Gestão > **Empresa** > aba **Auditoria**.",
          "Use **Filtrar por tipo de registro** para ver só um assunto (pessoas, ajustes, ausências, fechamentos…).",
          "Ficam registrados, entre outros: cadastros e alterações, decisões de pedidos (em destaque as decisões do próprio pedido), tratamentos, fechamentos e reaberturas, consultas de fotos, emissão de relatórios e arquivos fiscais.",
          "A auditoria não pode ser apagada nem editada.",
        ],
      },
    ],
  },

  // ───────────────────────────── Central do Ponto ─────────────────────────────
  {
    id: "central-usar",
    group: "Central do Ponto (tablet)",
    title: "Bater o ponto na Central",
    who: "Quem registra ponto na Central",
    need: ["punch"],
    summary: "Como se identificar no tablet da empresa (QR, código ou CPF), autorizar a foto e conferir a batida.",
    blocks: [
      {
        steps: [
          "Na tela inicial da Central, toque em **Aproxime o QR Code do crachá** e mostre o QR (do crachá impresso ou de Minha conta > **Meu crachá (QR)** no celular).",
          "Ou toque em **Digitar código ou CPF**, escolha **Código interno** ou **CPF**, digite no teclado e toque em OK.",
          "Se a empresa exige PIN (e você não usou o QR do celular), digite o seu **PIN**.",
          "Confira o seu nome e a **Próxima batida** e toque em **Registrar e tirar foto**. Olhe para a câmera: a foto é tirada em 3 segundos.",
          "Aparece **Batida registrada às HH:MM** com o NSR. O comprovante fica no aplicativo, em Registros.",
        ],
      },
      {
        list: [
          "Na primeira vez, a Central pede a autorização da foto: **Concordo e continuar**. Sem a autorização, use o aplicativo para registrar.",
          "Não é você? Toque em **Não sou [nome]**.",
          "Sem internet, a Central guarda a batida e a foto e mostra **Batida guardada**; ela é confirmada quando a conexão voltar (identificação só pelo QR nesse caso).",
          "A tela volta sozinha ao início depois de alguns segundos.",
        ],
      },
    ],
  },
  {
    id: "central-montar",
    group: "Central do Ponto (tablet)",
    title: "Preparar o tablet da Central",
    who: "Administração",
    need: ["kiosks.manage"],
    summary: "Como deixar um tablet pronto para ser o relógio de ponto da empresa.",
    blocks: [
      {
        steps: [
          "Use um tablet com câmera frontal, ligado na tomada e com internet (Wi-Fi da empresa).",
          "Cadastre a central em Gestão > Cadastros > Centrais e anote o código de pareamento (veja o tópico Centrais do Ponto).",
          "No navegador do tablet, abra o endereço do app seguido de **/central**, digite o código e toque em **Parear**.",
          "Permita o uso da câmera e da localização quando o navegador pedir.",
          "Toque em **Tela cheia** (no rodapé) e, se possível, fixe o navegador na tela (modo quiosque do tablet) para ninguém sair do app.",
          "Ajuste o tablet para a tela não apagar durante o expediente.",
        ],
      },
      { tip: "Se o tablet for trocado, gere um **Novo código de pareamento**. Se for perdido ou roubado, **Revogue** a central na hora." },
    ],
  },

  // ───────────────────────────── Dúvidas e glossário ─────────────────────────────
  {
    id: "faq",
    group: "Dúvidas e glossário",
    title: "Perguntas frequentes",
    who: "Todos",
    summary: "As dúvidas mais comuns de quem bate ponto e de quem faz a gestão.",
    blocks: [
      { h: "Bati o ponto duas vezes sem querer. E agora?", text: "Peça em Solicitações > Corrigir marcação > Bati por engano. A batida extra continua registrada, mas deixa de contar depois da aprovação." },
      { h: "Esqueci de bater a saída ontem.", text: "Peça em Solicitações > Corrigir marcação > Esqueci de bater, com a data, a hora e a marcação Saída. Enquanto isso o dia aparece como Incompleto." },
      { h: "O botão Registrar ponto está cinza.", text: "Ou a jornada do dia já foi encerrada (4ª batida feita), ou a empresa definiu que você bate ponto só na Central." },
      { h: "Fiquei sem internet. Perdi a batida?", text: "Não. Ela fica guardada no aparelho e é enviada quando a conexão voltar, desde que em até 72 horas. Não desinstale o app nesse meio tempo." },
      { h: "Por que tenho falta num dia em que não trabalho?", text: "A sua jornada provavelmente está com dias de trabalho errados, ou o feriado não foi cadastrado. Avise o RH." },
      { h: "Esqueci a senha.", text: "Peça ao RH uma nova senha temporária (Cadastros > Pessoas > Nova senha), ou entre com a conta Google vinculada." },
      { h: "Uma pessoa saiu da empresa.", text: "Desative o cadastro (Cadastros > Pessoas > Desativar). Não exclua: o histórico de ponto precisa ser guardado." },
      { h: "Preciso corrigir um mês já fechado.", text: "Reabra em Empresa > Fechamento, faça o Tratamento e feche de novo. Tudo fica na auditoria." },
      { h: "Quem aprova os pedidos de quem não tem gestor?", text: "O RH e a Administração." },
      { h: "A Administração pode aprovar o próprio pedido?", text: "Só quando ninguém mais na empresa pode decidir, e com justificativa obrigatória, que fica em destaque na auditoria." },
      { h: "A foto é obrigatória?", text: "No aplicativo, não: cada pessoa decide, e o ponto vale do mesmo jeito. Na Central, sim. As fotos são apagadas no fechamento do mês." },
    ],
  },
  {
    id: "glossario",
    group: "Dúvidas e glossário",
    title: "Glossário",
    who: "Todos",
    summary: "Os termos técnicos e legais que aparecem no aplicativo.",
    blocks: [
      {
        list: [
          "**REP-P**: Registrador Eletrônico de Ponto via Programa, o tipo de sistema de ponto previsto na Portaria MTP 671/2021. É o que este aplicativo é.",
          "**Marcação** ou **batida**: cada registro de entrada, intervalo, retorno ou saída. Nunca é apagada nem alterada.",
          "**NSR**: Número Sequencial de Registro. Toda marcação recebe um número único, em ordem, sem buracos.",
          "**Comprovante**: o documento de cada batida, com NSR, data, hora e o código de segurança.",
          "**Espelho de ponto**: o resumo do mês de uma pessoa, com as batidas, as horas e o saldo.",
          "**Folha de ponto**: a versão em uma página A4 do espelho, para assinatura.",
          "**Ajuste** (ou correção): pedido de incluir ou desconsiderar uma marcação. A original continua guardada.",
          "**Tratamento**: a correção feita diretamente pela gestão, com motivo.",
          "**Ausência justificada**: atestado, abono, férias, licença ou afastamento que dispensa a jornada do dia.",
          "**Saldo**: horas trabalhadas menos horas previstas. Positivo = horas extras; negativo = débito.",
          "**Tolerância**: os minutos de diferença por dia que não viram saldo (no máximo 10 por dia, pela CLT).",
          "**Banco de horas**: o acúmulo do saldo para compensar depois, dentro do prazo definido pela empresa.",
          "**Fechamento**: a trava do mês depois de conferido.",
          "**AFD**: Arquivo Fonte de Dados, com todas as marcações, para a fiscalização.",
          "**AEJ**: Arquivo Eletrônico de Jornada, com a jornada já tratada, para a fiscalização.",
          "**Central do Ponto**: o tablet da empresa usado como relógio de ponto coletivo.",
          "**2FA**: verificação em duas etapas, um código do celular além da senha.",
        ],
      },
    ],
  },
];
