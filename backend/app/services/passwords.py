"""Política de senha e senhas temporárias."""
import secrets

MIN_LENGTH = 10
# sem caracteres ambíguos (0/O, 1/l/I) para quem digita a senha temporária a partir de uma folha
_TEMP_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_temp() -> str:
    """Senha temporária de 12 caracteres (mostrada uma única vez; o usuário é obrigado a trocá-la)."""
    while True:
        password = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(12))
        # tem de passar na própria política (letras e números); sem isto ~11% saíam só com letras
        if any(c.isdigit() for c in password) and any(c.isalpha() for c in password):
            return password


def check_policy(new: str, current: str | None = None, email: str | None = None, cpf: str | None = None) -> str | None:
    """Mensagem de erro, ou None se a senha é aceitável."""
    if len(new) < MIN_LENGTH:
        return f"A senha deve ter ao menos {MIN_LENGTH} caracteres"
    if len(set(new)) < 4:
        return "A senha é simples demais"
    if not any(c.isalpha() for c in new) or not any(c.isdigit() for c in new):
        return "Use letras e números na senha"
    lowered = new.lower()
    if email and lowered in (email.lower(), email.lower().split("@")[0]):
        return "A senha não pode ser o seu e-mail"
    if cpf and cpf in new:
        return "A senha não pode conter o seu CPF"
    if current is not None and new == current:
        return "A nova senha deve ser diferente da atual"
    return None
