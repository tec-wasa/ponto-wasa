/** Funções puras da Central (testáveis sem navegador). */

export const onlyDigits = (s: string) => s.replace(/\D/g, "");

/** 12345678909 -> 123.456.789-09 (aceita entrada parcial). */
export function maskCpf(digits: string): string {
  const d = onlyDigits(digits).slice(0, 11);
  return d.replace(/^(\d{3})(\d)/, "$1.$2").replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1-$2");
}

/** Mostra o CPF/código sem expor tudo depois de um instante: só os 3 últimos dígitos ficam visíveis. */
export function hideDigits(digits: string, visible = 3): string {
  const d = onlyDigits(digits);
  return d.length <= visible ? d : "•".repeat(d.length - visible) + d.slice(-visible);
}

export type Method = "code" | "cpf";

/** Tamanho aceito para cada tipo de identificação. */
export function validIdentifier(method: Method, digits: string): boolean {
  const d = onlyDigits(digits);
  return method === "cpf" ? d.length === 11 : d.length >= 4 && d.length <= 8;
}

export const validPin = (pin: string) => /^\d{4,6}$/.test(pin);

/** Só QR do Ponto (crachá impresso ou rotativo do aplicativo) é aceito; qualquer outro código de barras é ignorado. */
export const looksLikePontoQr = (text: string) => /^(PB1\.\d+\.\d+\.\d+\.[0-9a-f]{20}|PR1\.\d+\.\d{6})$/.test(text.trim());

/** Marca de tempo do servidor -> "HH:MM" no fuso da empresa. */
export const clockText = (ms: number, tz: string) => new Date(ms).toLocaleTimeString("pt-BR", { timeZone: tz, hour: "2-digit", minute: "2-digit" });

/** Mensagem amigável para os erros mais comuns. */
export function friendly(status: number, message: string, code?: string): string {
  if (code === "day_closed") return "Jornada encerrada: a saída de hoje já foi registrada. Se precisar corrigir algo, peça um ajuste no aplicativo ou ao RH.";
  if (code === "ticket_invalid") return "A identificação expirou. Comece de novo.";
  if (code === "consent_required") return "Sem a autorização da foto não é possível registrar por esta central. Use o aplicativo.";
  if (status === 0) return "Sem conexão com o servidor. Aguarde e tente de novo.";
  if (status === 429) return "Muitas tentativas. Aguarde alguns minutos.";
  if (status === 503) return "Serviço temporariamente indisponível. Tente de novo em instantes.";
  return message;
}

/** Leitor USB/Bluetooth em modo "teclado" (o padrão de fábrica): "digita" o conteúdo do QR muito rápido e termina com Enter.
 *  Junta as teclas; uma pessoa digitando (intervalo grande entre teclas) nunca completa uma leitura. */
export class WedgeBuffer {
  private text = "";
  private last = 0;
  constructor(private readonly maxGapMs = 60, private readonly maxLen = 80) {}

  /** Devolve o texto lido quando chega o Enter de uma sequência rápida; senão, null. */
  feed(key: string, at: number): string | null {
    if (at - this.last > this.maxGapMs) this.text = ""; // pausa longa: recomeça (não é leitor)
    this.last = at;
    if (key === "Enter") {
      const out = this.text;
      this.text = "";
      return out.length >= 8 ? out : null;
    }
    if (key.length === 1 && this.text.length < this.maxLen) this.text += key;
    return null;
  }
}
