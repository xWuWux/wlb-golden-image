# Zarządzane przez Ansible (rola tljh) — audyt uprzywilejowanych akcji Administratora Klienta
# (IMG-003/#51, zdarzenia detekcyjne). Po ograniczeniu roli (plik 15-wlb-admin-role.py: bez
# access:servers i tokens) Administrator Klienta nie wchodzi już do serwera badacza ani nie działa
# jego tokenem (Z1–Z3 wyeliminowane), a nadanie pełnego admina jest odrzucane przez hub (Z5). Legalne
# pozostają operacje na kontach: zatwierdzanie, reset hasła badacza (Z4), nadanie/odebranie roli i grupy.
# Te żądania przekazujemy z logu huba do syslog pod STABILNYM tagiem wlb-hub-audit (-> journald -> SIEM)
# jako ślad rozliczalności (§21, §25) i sygnał detekcyjny. Filtr dopuszcza wyłącznie metody zmieniające
# i wrażliwe ścieżki huba — nie cały (głośny) access-log.
import logging
import re
import syslog

_WLB_AUDIT_RE = re.compile(
    r"\b(?:PATCH|POST|DELETE) /hub/(?:api/users/|api/groups/|change-password/|authorize/)"
)

# syslog.openlog ustawia realny identyfikator (SYSLOG_IDENTIFIER w journald); .ident w SysLogHandler
# tylko doklejałby tekst do treści i journalctl -t by go nie widział.
syslog.openlog(ident="wlb-hub-audit", facility=syslog.LOG_AUTHPRIV)


class _WlbAdminAudit(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # Audyt nie może wywrócić logowania huba — każdy błąd emisji połykamy cicho.
        try:
            message = record.getMessage()
            if _WLB_AUDIT_RE.search(message):
                syslog.syslog(syslog.LOG_NOTICE, message)
        except Exception:  # noqa: S110
            pass


logging.getLogger("JupyterHub").addHandler(_WlbAdminAudit())
