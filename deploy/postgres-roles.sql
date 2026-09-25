-- Papel de mínimo privilégio para a aplicação (PostgreSQL).
--
-- Rodar como dono do banco, DEPOIS de `alembic upgrade head`, trocando CHANGE_ME por uma senha forte.
-- A aplicação deve conectar com este papel (PONTO_DATABASE_URL), e NUNCA com o dono das tabelas:
-- assim, mesmo que o código da aplicação seja comprometido, ele não consegue alterar nem apagar
-- marcações e trilha de auditoria (sem UPDATE/DELETE/TRUNCATE) nem desativar os gatilhos (sem ALTER TABLE).
-- Migrações continuam rodando com o dono.
--
-- ATENÇÃO: este script é idempotente e deve ser reexecutado após qualquer migração que crie tabelas,
-- pois o papel só recebe privilégios sobre as tabelas listadas abaixo (o teste test_pg_roles falha se
-- uma tabela usada pela aplicação ficar de fora).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ponto_app') THEN
        CREATE ROLE ponto_app LOGIN PASSWORD 'CHANGE_ME' NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO ponto_app;

-- Tabelas mutáveis: sem DELETE (a aplicação desativa registros, não os apaga).
GRANT SELECT, INSERT, UPDATE ON companies, users, schedules, closings, adjustments, absences, nsr_counters, kiosks, kiosk_tickets TO ponto_app;

-- Append-only (ARP e auditoria): somente leitura e inserção.
-- Fotos das batidas: apagadas no fechamento do mês (retenção), por isso permitem DELETE.
GRANT SELECT, INSERT, DELETE ON punch_photos TO ponto_app;

GRANT SELECT, INSERT ON punches, arp_events, audit_log, hour_bank_entries TO ponto_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ponto_app;
