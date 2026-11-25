import { Link } from "react-router-dom";
import { useConfig } from "../google";

const UPDATED = "24/11/2026";

function useProvider() {
  const c = useConfig();
  return {
    name: c?.provider_name || "o fornecedor do sistema Ponto",
    email: c?.provider_email || null,
  };
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main style={{ maxWidth: 760 }}>
      <p className="small"><Link to="/">← Voltar ao Ponto</Link></p>
      <h1>{title}</h1>
      <p className="muted small">Última atualização: {UPDATED}</p>
      <article className="card legal">{children}</article>
    </main>
  );
}

/** /privacidade: política de privacidade (LGPD). Pública: o Google exige o link na tela de consentimento do login. */
export function Privacy() {
  const p = useProvider();
  return (
    <Shell title="Política de privacidade">
      <p>
        O <b>Ponto</b> é um sistema de registro eletrônico de ponto (REP-P, Portaria MTP 671/2021) fornecido por {p.name} às empresas
        que o contratam. Esta política explica quais dados pessoais são tratados, por quê e quais são os seus direitos, conforme a Lei
        Geral de Proteção de Dados (Lei 13.709/2018, LGPD).
      </p>

      <h2>Quem é responsável pelos seus dados</h2>
      <p>
        A <b>empresa em que você trabalha</b> é a <b>controladora</b>: ela decide cadastrar você e usar o sistema para controlar a
        jornada. {p.name} atua como <b>operador</b>, tratando os dados em nome da empresa e conforme as instruções dela. Dúvidas e pedidos
        sobre os seus dados devem ser feitos primeiro à sua empresa (ao RH ou ao encarregado de dados dela){p.email ? <>; o operador pode ser contatado em <a href={`mailto:${p.email}`}>{p.email}</a></> : ""}.
      </p>

      <h2>Quais dados são tratados</h2>
      <ul>
        <li><b>Cadastro:</b> nome, CPF, e-mail, cargo, data de admissão, jornada, gestor e código interno da Central.</li>
        <li><b>Marcações de ponto:</b> data, hora, tipo (entrada, intervalo, saída), número sequencial (NSR) e origem (aplicativo ou Central).</li>
        <li><b>Localização</b> no momento da marcação pelo aplicativo, quando você autoriza, e a distância até o posto na Central.</li>
        <li><b>Foto</b> no momento da marcação: obrigatória na Central e opcional no aplicativo (só com a sua autorização).</li>
        <li><b>Ajustes, ausências e banco de horas:</b> pedidos, justificativas, decisões e lançamentos. Não informe diagnóstico nem CID.</li>
        <li><b>Acesso:</b> endereço IP, data e hora de entrada e as ações feitas no sistema (trilha de auditoria).</li>
        <li><b>Login com Google:</b> se você usar o botão “Entrar com Google”, recebemos do Google apenas o seu nome, o seu e-mail e um
          identificador da conta. Não temos acesso à sua senha do Google, aos seus e-mails, arquivos ou contatos.</li>
      </ul>

      <h2>Para que e com qual base legal</h2>
      <ul>
        <li><b>Controlar a jornada de trabalho</b> e gerar os documentos exigidos (espelho de ponto, AFD, AEJ, comprovantes): cumprimento de
          obrigação legal (art. 7º, II, da LGPD; art. 74 da CLT e Portaria MTP 671/2021).</li>
        <li><b>Conferir a marcação</b> (foto e localização): legítimo interesse da empresa em evitar fraudes e, no aplicativo, o seu consentimento,
          que pode ser retirado a qualquer momento sem impedir o registro do ponto.</li>
        <li><b>Segurança e auditoria</b> (IP, trilha de ações, login): legítimo interesse e exercício regular de direitos.</li>
        <li><b>Atestados e outros dados de saúde:</b> só o necessário, visíveis apenas ao RH, para cumprir obrigações trabalhistas (art. 11, II, a).</li>
      </ul>

      <h2>Com quem os dados são compartilhados</h2>
      <p>
        Dentro da empresa, cada pessoa vê só o que a função dela permite (você, o seu gestor, o RH e a administração). Fora dela, os registros
        podem ser entregues ao Auditor-Fiscal do Trabalho, à Justiça ou a outras autoridades quando a lei exigir. O operador usa provedores de
        hospedagem e de rede contratados para manter o serviço no ar. Os dados não são vendidos nem usados para publicidade.
      </p>

      <h2>Por quanto tempo</h2>
      <p>
        Marcações, ajustes e a trilha de auditoria não são apagados nem alterados (exigência do REP-P) e são guardados pelo prazo exigido pela
        legislação trabalhista e fiscal. As fotos das marcações são apagadas quando o mês é fechado. Ao fim do contrato da empresa com o
        operador, os dados são devolvidos à empresa e eliminados do sistema, salvo o que a lei obrigar a manter.
      </p>

      <h2>Segurança</h2>
      <p>
        Conexão sempre criptografada (HTTPS), senhas guardadas de forma irreversível, fotos e segredos criptografados, controle de acesso por
        função, verificação em duas etapas, cópias de segurança e registros que não podem ser alterados (cadeia de hashes).
      </p>

      <h2>Cookies</h2>
      <p>
        Usamos apenas um cookie essencial, que mantém a sua sessão aberta com segurança. Não usamos cookies de publicidade nem de
        rastreamento. O botão “Entrar com Google” é carregado do Google e segue a política de privacidade do Google.
      </p>

      <h2>Seus direitos</h2>
      <p>
        Você pode pedir confirmação e acesso aos seus dados, correção de dados incompletos ou errados, informação sobre compartilhamentos e
        a revogação de consentimentos (foto e localização no aplicativo). Registros de ponto não podem ser apagados enquanto a lei exigir que
        sejam mantidos. Faça o pedido à sua empresa; se não for atendido, você pode procurar a Autoridade Nacional de Proteção de Dados (ANPD).
      </p>

      <h2>Mudanças</h2>
      <p>Esta política pode ser atualizada. A data da última versão fica no topo desta página.</p>
    </Shell>
  );
}

/** /termos: termos de uso. */
export function Terms() {
  const p = useProvider();
  return (
    <Shell title="Termos de uso">
      <p>
        Estes termos valem para quem usa o <b>Ponto</b>, sistema de registro eletrônico de ponto fornecido por {p.name} às empresas
        contratantes. Ao entrar no sistema, você concorda com eles e com a <Link to="/privacidade">Política de privacidade</Link>.
      </p>

      <h2>Para que serve</h2>
      <p>
        Registrar as marcações de ponto, acompanhar a jornada, pedir ajustes e justificar ausências e, para quem tem função de gestão,
        acompanhar a equipe, aprovar pedidos, manter os cadastros e gerar os documentos exigidos pela Portaria MTP 671/2021.
      </p>

      <h2>Quem pode usar</h2>
      <p>
        Só quem foi cadastrado pela empresa. Não há cadastro aberto. O acesso termina quando a empresa desativa o cadastro ou encerra o contrato.
      </p>

      <h2>Sua conta</h2>
      <ul>
        <li>O acesso é pessoal e intransferível: não compartilhe a sua senha, a sua conta Google, o seu código ou PIN da Central nem o seu crachá.</li>
        <li>Registre o ponto você mesmo, no momento real da entrada, intervalo e saída. Registrar por outra pessoa, ou com dados falsos, é falta
          grave e pode ter consequências trabalhistas e legais.</li>
        <li>Se perceber uso indevido da sua conta, avise a sua empresa imediatamente.</li>
      </ul>

      <h2>Marcações e correções</h2>
      <p>
        Cada marcação recebe um número sequencial e um comprovante, e não pode ser alterada nem apagada. Correções são feitas por pedido de
        ajuste, com justificativa, decididas por quem tem essa função na empresa; o registro original continua guardado.
      </p>

      <h2>Funcionamento sem internet</h2>
      <p>
        O aplicativo pode guardar a marcação sem conexão e enviá-la depois. Ela vale com a hora em que foi feita, dentro dos prazos e regras
        configurados pela empresa; fora deles, a correção é feita por pedido de ajuste.
      </p>

      <h2>Disponibilidade</h2>
      <p>
        O serviço é mantido com cópias de segurança e monitoramento, mas pode ter interrupções para manutenção ou por falhas de rede.
        Quando o aplicativo ou a Central não estiver disponível, siga a orientação da sua empresa para registrar a jornada.
      </p>

      <h2>Responsabilidades</h2>
      <p>
        A empresa contratante é responsável pelos cadastros, pelas regras de jornada e pelas decisões sobre ajustes e ausências. {p.name} é
        responsável por manter o sistema funcionando conforme a legislação do REP-P e por proteger os dados que trata em nome da empresa.
      </p>

      <h2>Contato</h2>
      <p>
        Dúvidas sobre a sua jornada, cadastro ou dados: procure a sua empresa.{p.email ? <> Sobre o sistema: <a href={`mailto:${p.email}`}>{p.email}</a>.</> : ""}
      </p>
    </Shell>
  );
}
