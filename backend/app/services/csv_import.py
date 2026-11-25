"""Importação de colaboradores por CSV (Excel em português ou UTF-8), validada linha a linha, tudo ou nada."""
import base64
import binascii
import csv
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Schedule, User
from .cpf import digits, is_valid_cpf

MAX_ROWS = 200  # cada linha gera um hash de senha (argon2, de propósito lento): limita o tempo da requisição
MAX_BYTES = 1_000_000

# Cabeçalhos aceitos (sem acento, minúsculos, sem espaços): aliases -> campo
ALIASES = {
    "nome": "name", "nomecompleto": "name", "name": "name",
    "email": "email", "e-mail": "email", "emailcorporativo": "email",
    "cpf": "cpf",
    "codigo": "code", "codigointerno": "code", "matricula": "code",
    "cargo": "job_title", "funcao": "job_title", "cargofuncao": "job_title", "cargo/funcao": "job_title",
    "gestor": "manager", "emaildogestor": "manager", "emailgestor": "manager", "gestoremail": "manager",
    "jornada": "schedule", "horario": "schedule",
    "perfil": "role", "papel": "role",
    "admissao": "admitted_at", "dataadmissao": "admitted_at", "dataadmissao_": "admitted_at", "dtadmissao": "admitted_at",
}
REQUIRED = ("name", "email", "cpf")
ROLE_ALIASES = {
    "colaborador": "employee", "empregado": "employee", "funcionario": "employee", "employee": "employee",
    "gestor": "manager", "manager": "manager", "rh": "hr", "hr": "hr", "admin": "admin", "administrador": "admin",
    "auditor": "auditor",
}
TEMPLATE = (
    "nome;email;cpf;cargo;gestor;jornada;perfil;admissao;codigo\n"
    "Ana Souza;ana@empresa.com.br;529.982.247-25;Analista Contábil;gil@empresa.com.br;Comercial 8h;colaborador;15/03/2024;\n"
)


@dataclass
class RowError:
    line: int
    field: str
    message: str


@dataclass
class ParsedRow:
    line: int
    name: str = ""
    email: str = ""
    cpf: str = ""
    job_title: str | None = None
    manager_email: str | None = None
    schedule_id: int | None = None
    role: str = "employee"
    admitted_at: date | None = None
    code: str | None = None


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    total: int = 0


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in text if c.isalnum() or c == "/")


def decode_payload(b64: str) -> str:
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Arquivo inválido (não foi possível ler o conteúdo)") from None
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Arquivo grande demais (máximo de {MAX_BYTES // 1000} KB)")
    for encoding in ("utf-8-sig", "cp1252"):  # Excel em português costuma salvar em cp1252
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Não foi possível identificar a codificação do arquivo (use UTF-8)")


def _parse_date(text: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse(db: Session, company_id: int, text: str, allowed_roles: tuple[str, ...]) -> ParseResult:
    result = ParseResult()
    # Linhas em branco, inclusive as que o Excel salva só com separadores (";;;;;"), são ignoradas; a numeração das
    # linhas continua a do arquivo, para o erro apontar a linha certa.
    all_lines = text.splitlines()
    first = next((ln for ln in all_lines if ln.strip()), None)
    if first is None:
        result.errors.append(RowError(1, "arquivo", "O arquivo está vazio"))
        return result
    delimiter = ";" if first.count(";") >= first.count(",") else ","
    numbered = [(n, cells) for n, cells in enumerate(csv.reader(all_lines, delimiter=delimiter), start=1)
                if any(c.strip() for c in cells)]
    if not numbered:
        result.errors.append(RowError(1, "arquivo", "O arquivo está vazio"))
        return result
    reader = [cells for _, cells in numbered]
    line_of = [n for n, _ in numbered]

    header = [ALIASES.get(_norm(h)) for h in reader[0]]
    missing = [f for f in REQUIRED if f not in header]
    if missing:
        labels = {"name": "nome", "email": "email", "cpf": "cpf"}
        result.errors.append(RowError(1, "cabeçalho", "Faltam as colunas: " + ", ".join(labels[m] for m in missing)))
        return result
    data = reader[1:]
    result.total = len(data)
    if not data:
        result.errors.append(RowError(1, "arquivo", "Não há linhas de dados"))
        return result
    if len(data) > MAX_ROWS:
        result.errors.append(RowError(1, "arquivo", f"O arquivo tem {len(data)} linhas; o máximo por importação é {MAX_ROWS}"))
        return result

    schedules = {_norm(s.name): s.id for s in db.execute(select(Schedule).where(Schedule.company_id == company_id)).scalars()}
    existing_emails = {e for (e,) in db.execute(select(User.email)).all()}  # e-mail é único no sistema todo
    existing_cpfs = {c for (c,) in db.execute(select(User.cpf).where(User.company_id == company_id)).all()}
    seen_emails: dict[str, int] = {}
    seen_cpfs: dict[str, int] = {}
    seen_codes: dict[str, int] = {}
    existing_codes = {c for (c,) in db.execute(select(User.employee_code).where(
        User.company_id == company_id, User.employee_code.is_not(None))).all()}
    parsed: list[ParsedRow] = []  # todas as linhas, mesmo as com erro: o gestor é validado em todas

    for offset, raw in enumerate(data):
        line = line_of[offset + 1]  # número da linha no arquivo (a primeira com conteúdo é o cabeçalho)
        cells = {header[i]: (raw[i].strip() if i < len(raw) else "") for i in range(len(header)) if header[i]}
        row = ParsedRow(line=line)

        def err(field_name: str, message: str, _line=line):
            result.errors.append(RowError(_line, field_name, message))

        row.name = cells.get("name", "")
        if len(row.name) < 2:
            err("nome", "Informe o nome")
        if len(row.name) > 200:
            err("nome", "Nome com mais de 200 caracteres")

        email = cells.get("email", "").lower()
        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            err("email", f"E-mail inválido: {cells.get('email', '')!r}")
            email = ""
        if email:
            if email in existing_emails:
                err("email", "E-mail já cadastrado no sistema")
            elif email in seen_emails:
                err("email", f"E-mail repetido no arquivo (linha {seen_emails[email]})")
            seen_emails.setdefault(email, line)
        row.email = email

        cpf_raw = cells.get("cpf", "")
        if not is_valid_cpf(cpf_raw):
            err("cpf", f"CPF inválido: {cpf_raw!r}")
        else:
            row.cpf = digits(cpf_raw)
            if row.cpf in existing_cpfs:
                err("cpf", "CPF já cadastrado nesta empresa")
            elif row.cpf in seen_cpfs:
                err("cpf", f"CPF repetido no arquivo (linha {seen_cpfs[row.cpf]})")
            seen_cpfs.setdefault(row.cpf, line)

        role_text = cells.get("role", "")
        if role_text:
            role = ROLE_ALIASES.get(_norm(role_text))
            if not role:
                err("perfil", f"Perfil desconhecido: {role_text!r} (use colaborador, gestor, rh, admin ou auditor)")
            elif role not in allowed_roles:
                err("perfil", f"Seu perfil não pode criar usuários '{role_text}' (só o administrador)")
            else:
                row.role = role

        sched_text = cells.get("schedule", "")
        if sched_text:
            sid = schedules.get(_norm(sched_text))
            if sid is None:
                err("jornada", f"Jornada não encontrada: {sched_text!r}. Cadastre-a antes em Gestão → Jornadas")
            row.schedule_id = sid

        adm_text = cells.get("admitted_at", "")
        if adm_text:
            row.admitted_at = _parse_date(adm_text)
            if row.admitted_at is None:
                err("admissão", f"Data inválida: {adm_text!r} (use dd/mm/aaaa)")

        code = cells.get("code", "")
        if code:
            if not (code.isdigit() and 4 <= len(code) <= 10):
                err("codigo", f"Código inválido: {code!r} (de 4 a 10 números)")
            elif code in existing_codes:
                err("codigo", "Código já usado nesta empresa")
            elif code in seen_codes:
                err("codigo", f"Código repetido no arquivo (linha {seen_codes[code]})")
            else:
                row.code = code
            seen_codes.setdefault(code, line)

        row.job_title = (cells.get("job_title") or "")[:100] or None
        row.manager_email = cells.get("manager", "").lower() or None
        parsed.append(row)

    # gestor: precisa existir na empresa ou estar no próprio arquivo (e ter perfil de chefia)
    by_email = {e: (r, i) for e, r, i in db.execute(
        select(User.email, User.role, User.id).where(User.company_id == company_id)).all()}
    in_file = {r.email: r.role for r in parsed if r.email}
    for row in parsed:
        if not row.manager_email:
            continue
        role = in_file.get(row.manager_email) or (by_email[row.manager_email][0] if row.manager_email in by_email else None)
        if role is None:
            result.errors.append(RowError(row.line, "gestor", f"Gestor não encontrado: {row.manager_email!r} (cadastre-o antes ou inclua-o no arquivo)"))
        elif role not in ("manager", "hr", "admin"):
            result.errors.append(RowError(row.line, "gestor", f"{row.manager_email!r} não tem perfil de gestor"))
    result.errors.sort(key=lambda e: e.line)
    bad_lines = {e.line for e in result.errors}
    result.rows = [r for r in parsed if r.line not in bad_lines]
    return result
