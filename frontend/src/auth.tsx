import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, clearApiCache, getTokens, setTokens } from "./api";
import type { Company, Permission, TwoFactorStatus, User } from "./types";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

interface AuthState {
  user: User | null;
  company: Company | null;
  twoFactor: TwoFactorStatus | null;
  /** "password_change_required" | "two_factor_required" | null: enquanto houver pendência, só a tela de conta funciona */
  restriction: string | null;
  loading: boolean;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  logout: () => void;
  reload: () => Promise<void>;
  /** A pessoa pode fazer esta ação? (única regra de exibição; o servidor confere de novo) */
  can: (p: Permission) => boolean;
  /** Tem alguma permissão de gestão (área Gestão)? */
  manages: boolean;
  /** Troca a sessão por uma nova (depois de trocar a senha ou mudar o 2FA, as demais sessões caem). */
  applyTokens: (t: TokenPair) => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [twoFactor, setTwoFactor] = useState<TwoFactorStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!getTokens()) {
      setUser(null);
      setCompany(null);
      setTwoFactor(null);
      return;
    }
    try {
      const [u, tf] = await Promise.all([api<User>("/auth/me"), api<TwoFactorStatus>("/auth/2fa")]);
      const restricted = u.must_change_password || (tf.required && !tf.enabled);
      // Com pendência, o servidor só libera a conta. Tudo é gravado junto: um estado "sem pendência, mas sem
      // empresa" derrubaria as telas que assumem a empresa carregada.
      const c = restricted ? null : await api<Company>("/company");
      setUser(u);
      setTwoFactor(tf);
      setCompany(c);
    } catch {
      setUser(null);
      setCompany(null);
      setTwoFactor(null);
    }
  }, []);

  useEffect(() => {
    reload().finally(() => setLoading(false));
    window.addEventListener("ponto:restricted", reload);
    return () => window.removeEventListener("ponto:restricted", reload);
  }, [reload]);

  const login = useCallback(
    async (email: string, password: string, otp?: string) => {
      const t = await api<TokenPair>("/auth/login", { method: "POST", body: { email, password, otp: otp || undefined } });
      clearApiCache(); // nada de dados em cache de outro usuário no mesmo aparelho
      setTokens({ access: t.access_token, refresh: t.refresh_token });
      await reload();
    },
    [reload],
  );

  const applyTokens = useCallback(
    async (t: TokenPair) => {
      setTokens({ access: t.access_token, refresh: t.refresh_token });
      clearApiCache();
      await reload();
    },
    [reload],
  );

  const logout = useCallback(() => {
    setTokens(null);
    clearApiCache();
    setUser(null);
    setCompany(null);
    setTwoFactor(null);
  }, []);

  const restriction = user?.must_change_password
    ? "password_change_required"
    : twoFactor && twoFactor.required && !twoFactor.enabled
      ? "two_factor_required"
      : null;

  const can = useCallback((p: Permission) => !!user?.permissions?.includes(p), [user]);
  const manages = !!user?.permissions?.some((p) => p !== "punch");

  const value = useMemo(
    () => ({ user, company, twoFactor, restriction, loading, login, logout, reload, applyTokens, can, manages }),
    [user, company, twoFactor, restriction, loading, login, logout, reload, applyTokens, can, manages],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth fora do AuthProvider");
  return v;
}
