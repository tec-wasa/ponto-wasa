from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PONTO_", env_file=".env")

    database_url: str = "sqlite:///./ponto.db"
    # Trocar em produção via PONTO_SECRET_KEY (>= 32 caracteres).
    secret_key: str = "dev-only-secret-change-me-in-production-0000"
    access_minutes: int = 60 * 8
    refresh_days: int = 14
    # Identificação do programa (REP-P e programa de tratamento), exigida nos cabeçalhos do AFD e do AEJ.
    inpi_number: str = ""  # nº do registro do programa de computador no INPI (17 dígitos), Art. 91
    dev_id: str = ""  # CNPJ (14) ou CPF (11) do desenvolvedor
    dev_name: str = ""
    dev_email: str = ""
    program_name: str = "Ponto"
    program_version: str = "0.3.0"  # até 8 caracteres

    # Modo de teste: permite gerar AFD/AEJ sem INPI e sem identificação do desenvolvedor (usa zeros).
    # Os arquivos NÃO são válidos para fiscalização; toda saída é sinalizada. Nunca ligar em produção.
    allow_missing_inpi: bool = False

    # Certificado ICP-Brasil (PKCS#12) para assinar AFD/AEJ (Art. 88). Sem ele, só gera os arquivos sem assinatura.
    signing_p12_path: str = ""
    signing_p12_password: str = ""

    # Sincronismo com a Hora Legal Brasileira (Anexo IX, item 2: variação máxima de 30 s).
    clock_check_enabled: bool = False
    # Registro off-line (Anexo IX, itens 4 e 5): o PWA guarda a marcação no aparelho e a envia depois.
    # Fotos das batidas: pasta local (criptografadas) e tamanho máximo. Na nuvem, troque o armazenamento em services/photos.py.
    photo_dir: str = "./photos"
    # Onde guardar as fotos: "local" (pasta acima) ou "s3" (qualquer bucket S3-compatível: AWS S3, Cloudflare R2, Backblaze B2, MinIO).
    photo_store: str = "local"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""  # vazio = AWS; R2/B2/MinIO: o endereço do serviço
    s3_region: str = ""  # AWS: sa-east-1 (São Paulo); R2: "auto"
    s3_prefix: str = "fotos/"
    s3_access_key_id: str = ""  # vazio = cadeia padrão do boto3 (papel IAM da máquina, variáveis AWS_*)
    s3_secret_access_key: str = ""
    s3_sse: str = "AES256"  # criptografia no servidor além da da aplicação; vazio desliga (provedor sem suporte)
    s3_path_style: bool = False  # MinIO e alguns provedores exigem endereçamento por caminho
    photo_max_bytes: int = 400_000
    # Central do Ponto
    kiosk_max_per_company: int = 5
    kiosk_ticket_seconds: int = 60
    kiosk_pairing_minutes: int = 15
    kiosk_pin_max_fails: int = 5
    kiosk_pin_lock_minutes: int = 5
    kiosk_default_radius_m: int = 100
    offline_punch_enabled: bool = True
    offline_max_hours: int = 72  # prazo máximo entre a marcação e o envio; depois disso, só por ajuste com aprovação
    ntp_server: str = "a.st1.ntp.br"
    max_clock_drift_seconds: float = 30.0

    # Verificação em duas etapas
    google_client_id: str = ""  # ID do cliente OAuth (tipo Aplicativo da Web) do Google Cloud; vazio = sem "Entrar com Google"
    cookie_secure: bool = True  # cookie da sessão só em HTTPS (desligar só em testes/desenvolvimento sem HTTPS)
    totp_key: str = ""  # chave que cifra os segredos TOTP (padrão: derivada de SECRET_KEY)
    require_2fa_roles: str = ""  # perfis obrigados a ter 2FA, separados por vírgula (ex.: "hr,admin")

    @property
    def require_2fa_role_set(self) -> set[str]:
        return {r.strip() for r in self.require_2fa_roles.split(",") if r.strip()}

    # Operação
    log_json: bool = False  # logs em JSON (uma linha por evento), recomendado em produção
    log_level: str = "INFO"
    docs_enabled: bool = True  # /docs e /redoc; desligar em produção
    login_max_failures: int = 5  # falhas de login por e-mail dentro da janela
    login_max_failures_per_ip: int = 30  # teto por IP (alto: um escritório inteiro divide o mesmo IP)
    login_window_minutes: int = 15

    # Criar tabelas automaticamente (create_all). Padrão: só em SQLite (desenvolvimento).
    # Em PostgreSQL o esquema vem exclusivamente das migrações: `alembic upgrade head`.
    auto_create_tables: bool | None = None

    @property
    def create_tables(self) -> bool:
        if self.auto_create_tables is not None:
            return self.auto_create_tables
        return self.database_url.startswith("sqlite")


settings = Settings()
