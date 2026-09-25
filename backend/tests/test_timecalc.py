from dataclasses import replace
from datetime import date, datetime, timedelta

from app.services.timecalc import ScheduleRule, compute_month

TZ = "America/Sao_Paulo"  # UTC-3 (sem horário de verão desde 2019)
RULE = ScheduleRule()
TODAY = date(2026, 9, 30)


def utc(day, h, m=0, month=8):
    """Hora LOCAL de São Paulo -> UTC naive."""
    return datetime(2026, month, day) + timedelta(hours=h + 3, minutes=m)


def day(results, d):
    return next(r for r in results if r.date == date(2026, 8, d))


def run(punches, rule=RULE):
    return compute_month(punches, rule, TZ, 2026, 8, TODAY)


NIGHT = replace(RULE, crosses_midnight=True)  # jornada que pode terminar no dia seguinte


def test_full_day_no_balance():
    r = run([(utc(3, 8), "entrada"), (utc(3, 12), "saida"), (utc(3, 13), "entrada"), (utc(3, 17), "saida")])
    d = day(r, 3)  # segunda
    assert d.worked == 480 and d.balance == 0 and d.status == "ok"


def test_overtime_counted():
    r = run([(utc(4, 8), "entrada"), (utc(4, 12), "saida"), (utc(4, 13), "entrada"), (utc(4, 18), "saida")])
    assert day(r, 4).balance == 60


def test_tolerance_absorbs_small_difference():
    r = run([(utc(5, 8), "entrada"), (utc(5, 12), "saida"), (utc(5, 13), "entrada"), (utc(5, 17, 8), "saida")])
    assert day(r, 5).worked == 488 and day(r, 5).balance == 0


def test_beyond_tolerance_is_counted():
    r = run([(utc(5, 8), "entrada"), (utc(5, 12), "saida"), (utc(5, 13), "entrada"), (utc(5, 17, 20), "saida")])
    assert day(r, 5).balance == 20


def test_absence_on_working_day():
    assert day(run([]), 6).status == "falta" and day(run([]), 6).balance == -480


def test_weekend_is_folga():
    assert day(run([]), 1).status == "folga"  # sábado


def test_open_entry_is_incomplete():
    r = run([(utc(7, 8), "entrada")])
    assert day(r, 7).status == "incompleto" and day(r, 7).warnings


def test_night_shift_belongs_to_start_day():
    r = run([(utc(10, 22), "entrada"), (utc(11, 6), "saida")], NIGHT)
    assert day(r, 10).worked == 480 and day(r, 11).worked == 0


def test_by_default_the_shift_ends_at_midnight_and_the_open_entry_is_incomplete():
    # sem a opção "vira a meia-noite": a entrada de 22h fica sem saída e a saída de 06h não é pareada com ela
    r = run([(utc(10, 22), "entrada"), (utc(11, 6), "saida")])
    assert day(r, 10).worked == 0 and day(r, 10).status == "incompleto" and day(r, 11).worked == 0
    # o dia seguinte recomeça limpo: entrada e saída normais valem
    r = run([(utc(10, 22), "entrada"), (utc(11, 8), "entrada"), (utc(11, 17), "saida")])
    assert day(r, 10).status == "incompleto" and day(r, 11).worked == 540


def test_short_interval_warning():
    r = run([(utc(12, 8), "entrada"), (utc(12, 12), "saida"), (utc(12, 12, 15), "entrada"), (utc(12, 16, 15), "saida")])
    assert any("intervalo" in w for w in day(r, 12).warnings)


def test_no_interval_over_six_hours_warns():
    r = run([(utc(13, 8), "entrada"), (utc(13, 16), "saida")])
    assert any("intervalo" in w for w in day(r, 13).warnings)


def test_days_before_admission_are_not_absences():
    r = compute_month([], RULE, TZ, 2026, 8, TODAY, start=date(2026, 8, 20))
    assert day(r, 10).status == "anterior" and day(r, 10).balance == 0 and day(r, 10).expected == 0
    assert day(r, 21).status == "falta"  # sexta, depois da admissão


def test_punch_before_admission_date_is_still_computed():
    r = compute_month([(utc(10, 8), "entrada"), (utc(10, 17), "saida")], RULE, TZ, 2026, 8, TODAY, start=date(2026, 8, 20))
    assert day(r, 10).status == "ok" and day(r, 10).worked == 540


def test_future_days_have_no_balance():
    r = compute_month([], RULE, TZ, 2026, 8, date(2026, 8, 10))
    assert day(r, 20).status == "futuro" and day(r, 20).balance == 0


def test_night_hour_is_reduced_for_22h_to_5h():
    # 22:00 às 06:00 = 8 h reais; 7 h (22h-5h) são noturnas => 420 min valem 480 => 540 min de duração
    r = run([(utc(10, 22), "entrada"), (utc(11, 6), "saida")], NIGHT)
    d = day(r, 10)
    assert d.worked == 480 and d.night_minutes == 420 and d.reduced_minutes == 540


def test_daytime_shift_has_no_night_reduction():
    d = day(run([(utc(4, 8), "entrada"), (utc(4, 17), "saida")]), 4)
    assert d.night_minutes == 0 and d.reduced_minutes == d.worked == 540


def test_partial_night_overlap():
    d = day(run([(utc(5, 20), "entrada"), (utc(5, 23), "saida")]), 5)  # 20h-23h: só 22h-23h é noturna
    assert d.night_minutes == 60 and d.reduced_minutes == 180 - 60 + round(60 * 60 / 52.5)
