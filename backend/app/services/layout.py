"""Formatação de campos de largura fixa (AFD) e delimitados (AEJ), texto ISO 8859-1 com CRLF."""
import unicodedata

# --- Hipóteses de interpretação (a Portaria não especifica; validar na homologação) ------------
# H3. Campo numérico (N): alinhado à direita com zeros à esquerda (prática do setor).
#     Campo alfanumérico (A): alinhado à esquerda, completado com espaços à direita.
# H4. CRC-16 = CRC-16/ARC (polinômio 0xA001 refletido, valor inicial 0), calculado sobre o texto do
#     registro sem o próprio campo do CRC, em hexadecimal maiúsculo com 4 caracteres.
CRLF = "\r\n"


def latin1_safe(text: str) -> str:
    """Remove quebras/controle e troca o que não existe em ISO 8859-1 (ex.: emoji) por '?'."""
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in unicodedata.normalize("NFC", text))
    return text.encode("latin-1", "replace").decode("latin-1")


def num(value: int | str, width: int) -> str:
    s = str(int(value)) if str(value).strip() != "" else "0"
    if len(s) > width:
        raise ValueError(f"valor numérico {s!r} excede {width} posições")
    return s.zfill(width)


def alpha(value: str | None, width: int) -> str:
    return latin1_safe(value or "")[:width].ljust(width)


def crc16(data: str) -> str:
    crc = 0x0000
    for byte in data.encode("latin-1"):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return f"{crc:04X}"


def encode(lines: list[str]) -> bytes:
    return "".join(line + CRLF for line in lines).encode("latin-1")


def field(value: str | None, max_len: int) -> str:
    """Campo do AEJ: sem o delimitador '|', truncado no tamanho máximo."""
    return latin1_safe(value or "").replace("|", " ")[:max_len]
