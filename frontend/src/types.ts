export type Role = "employee" | "manager" | "hr" | "admin" | "auditor";

export type Permission =
  | "punch" | "company.settings" | "people.permissions" | "people.manage" | "people.list" | "schedules.manage"
  | "kiosks.manage" | "kiosks.view" | "badges.manage" | "absences.register" | "hourbank.entries" | "approvals"
  | "team.view" | "closing.manage" | "closing.view" | "fiscal.export" | "integrity.view" | "photos.view"
  | "reports.company" | "audit.view";

export interface User {
  id: number;
  name: string;
  email: string | null; // vazio = só bate ponto na Central
  cpf: string;
  role: Role;
  roles?: Role[]; // funções de gestão acumuláveis (admin, hr, manager; auditor sozinho)
  tracks_time?: boolean; // false: cadastro só de gestão, não registra ponto
  app_access?: boolean; // false: só bate ponto na Central, sem login
  permissions?: Permission[]; // só em /auth/me: o que a pessoa pode fazer (backend/app/permissions.py)
  scope?: "self" | "team" | "company"; // alcance na gestão
  google_linked?: boolean; // só em /auth/me
  login_method?: "pwd" | "google"; // como entrou nesta sessão
  restriction?: string | null; // pendência de segurança desta sessão
  manager_id: number | null;
  schedule_id: number | null;
  active: boolean;
  gps_consent_at: string | null;
  photo_consent_at?: string | null;
  punch_policy?: string; // "both" (padrão) ou "kiosk" (só a Central)
  admitted_at: string | null;
  job_title: string | null;
  hour_bank_enabled: boolean;
  hour_bank_start: string | null;
  must_change_password: boolean;
  totp_enabled: boolean;
}

export interface Company {
  id: number;
  name: string;
  cnpj: string;
  caepf: string | null;
  cno: string | null;
  bank_max_minutes: number | null;
  bank_expiry_months: number;
  timezone: string;
  workplace: string | null;
  photo_enabled?: boolean;
  kiosk_pin_required?: boolean;
  password_login?: boolean; // false: só "Entrar com Google"
}

export interface Kiosk {
  id: number;
  name: string;
  latitude: number | null;
  longitude: number | null;
  radius_m: number;
  active: boolean;
  paired: boolean;
  pairing_pending: boolean;
  last_seen_at: string | null;
  revoked_at: string | null;
  punches_today?: number;
}

export interface Punch {
  id: number;
  nsr: number;
  kind: string;
  occurred_at: string; // UTC, sem sufixo
  collector: string;
  offline: boolean;
  latitude: number | null;
  longitude: number | null;
  accuracy_m: number | null;
  device_id: string | null;
  hash: string;
  origin: string; // "Aplicativo" ou "Central <nome>"
}

export interface Receipt {
  title: string;
  employer: string;
  cnpj: string;
  caepf_cno: string | null;
  workplace: string | null;
  inpi: string;
  employee: string;
  cpf: string;
  nsr: number;
  kind: string;
  occurred_at_local: string;
  hash: string;
}

export interface MirrorDay {
  date: string;
  expected: number;
  worked: number;
  balance: number;
  status: "ok" | "folga" | "falta" | "incompleto" | "hoje" | "futuro" | "anterior" | "justificada";
  justification?: string | null;
  punches: string[];
  warnings: string[];
}

export interface Mirror {
  user_id: number;
  month: string;
  totals: {
    worked_minutes: number;
    expected_minutes: number;
    balance_minutes: number;
    absences: number;
    justified_days: number;
    incomplete_days: number;
  };
  days: MirrorDay[];
}

export interface Adjustment {
  id: number;
  user_id: number;
  kind: "incluir" | "desconsiderar";
  requested_at: string | null;
  punch_kind: string | null;
  target_punch_id: number | null;
  reason: string;
  status: "pending" | "approved" | "rejected" | "revoked";
  decided_by: number | null;
  decision_note: string | null;
  user_name?: string | null;
  target_kind?: string | null;
  target_at?: string | null;
  can_decide?: boolean; // quem vê pode aprovar/rejeitar
  self_decision?: boolean; // ... e seria autoaprovação (justificativa obrigatória)
}

export interface Schedule {
  id: number;
  name: string;
  weekdays: string;
  daily_minutes: number;
  break_minutes: number;
  tolerance_minutes: number;
  start_time: string;
  break_start: string;
  crosses_midnight?: boolean;
}

export interface AuditRow {
  id: number;
  at: string;
  actor_id: number | null;
  action: string;
  entity: string;
  entity_id: string | null;
  before: unknown;
  after: unknown;
  ip: string | null;
}

export interface Closing {
  month: string;
  status: "closed" | "open";
  closed_at: string | null;
}

export interface BankAlert { code: string; message: string }

export interface BankSummary {
  user_id: number;
  enabled: boolean;
  balance: number;
  alerts: BankAlert[];
  since?: string;
  automatic?: number;
  credits?: number;
  compensations?: number;
  limit_minutes?: number | null;
  expiry_months?: number;
  at_risk_minutes?: number;
}

export interface BankStatement {
  enabled: boolean;
  opening: number;
  closing: number;
  lines: { date: string; minutes: number; source: "automatico" | "lancamento"; description: string; balance: number }[];
}

export interface DashboardPerson {
  user_id: number;
  name: string;
  job_title: string | null;
  state: string;
  state_label: string;
  first_entry: string | null;
  last_punch: string | null;
  worked_minutes: number;
  late_minutes: number;
  no_schedule: boolean;
  bank_balance?: number;
  bank_alerts?: BankAlert[];
}

export interface Dashboard {
  as_of: string;
  date: string;
  summary: {
    total: number;
    sem_marcacao: number;
    incompleto: number;
    presente: number;
    em_intervalo: number;
    aguardando: number;
    saiu: number;
    justificada: number;
    folga: number;
    late: number;
    pending_adjustments: number;
    bank_alerts: number;
  };
  people: DashboardPerson[];
}

export interface Absence {
  id: number;
  user_id: number;
  user_name: string | null;
  kind: string;
  kind_label: string;
  start_date: string;
  end_date: string;
  minutes: number | null;
  reason: string | null;
  attachment_name: string | null;
  restricted: boolean;
  status: "pending" | "approved" | "rejected" | "cancelled";
  decided_by: number | null;
  decision_note: string | null;
  created_by: number;
  can_decide?: boolean;
  self_decision?: boolean;
}

export interface TwoFactorStatus {
  enabled: boolean;
  recovery_codes_left: number;
  required: boolean;
}

export interface ImportResult {
  dry_run: boolean;
  total: number;
  valid: number;
  imported: boolean;
  created: number;
  errors: { line: number; field: string; message: string }[];
  preview: { line: number; name: string; email: string; role: string; manager: string | null }[];
  credentials: { name: string; email: string; password: string }[];
}
