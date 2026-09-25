"""Sincronismo com a Hora Legal Brasileira (Anexo IX, item 2: variação máxima de 30 segundos)."""
import socket
import struct
import time
from dataclasses import dataclass

from ..config import settings

_NTP_EPOCH_OFFSET = 2208988800
_CACHE_SECONDS = 60.0


@dataclass
class ClockStatus:
    ok: bool
    drift_seconds: float | None  # relógio do NTP menos o local; None se não foi possível consultar
    server: str
    checked_at: float


_cache: ClockStatus | None = None


def query_ntp_offset(server: str, timeout: float = 3.0) -> float:
    """Consulta SNTP simples e devolve (hora do servidor NTP - hora local) em segundos."""
    packet = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t0 = time.time()
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(48)
        t3 = time.time()
    secs, frac = struct.unpack("!II", data[40:48])
    return (secs - _NTP_EPOCH_OFFSET + frac / 2**32) - (t0 + t3) / 2


def clock_status(force: bool = False) -> ClockStatus:
    global _cache
    now = time.time()
    if not force and _cache and now - _cache.checked_at < _CACHE_SECONDS:
        return _cache
    try:
        drift = query_ntp_offset(settings.ntp_server)
        status = ClockStatus(abs(drift) <= settings.max_clock_drift_seconds, drift, settings.ntp_server, now)
    except OSError:
        status = ClockStatus(True, None, settings.ntp_server, now)  # sem resposta do NTP: não bloqueia, só sinaliza
    _cache = status
    return status
