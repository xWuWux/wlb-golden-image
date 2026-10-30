# Code Review Notes

**Data:** 2026-09-28  
**Recenzent:** AI Assistant  
**PR #28:** Kolejka eksportu na dysku roboczym (#4) i NTP z lab.env (#5)  
**PR #1:** Pipeline CI w 6 etapach, testy jednostkowe i test migracji

---

## Weryfikacja uwag (2026-09-28)

Po analizie kodu na gałęziach PR, niektóre uwagi zostały skorygowane:

### PR #28 - Status uwag:

| # | Uwaga | Status | Priorytet |
|---|-------|--------|-----------|
| 1 | Brak logowania błędów chrony | ⚠️ Częściowo trafna | P2 |
| 2 | Race condition z mountem | ❌ Nietrafna | - |
| 3 | Walidacja NTP (IPv6, składnia chrony) | ✅ Trafna | P1 |
| 4 | Brak testu synchronizacji NTP | ✅ Trafna | P3 |

### PR #1 - Status uwag:

| # | Uwaga | Status | Priorytet |
|---|-------|--------|-----------|
| 1 | Walidacja schematu OTLP | ⚠️ Częściowo trafna | P3 |
| 2 | Wyciek tokenów i haseł | ⚠️ Częściowo trafna | P2 |
| 3 | Brak ponawiania eksportu | ✅ Trafna | P1 |
| 4 | Domyślny adres OTLP | ❌ Nietrafna | - |

---

## PR #28: Kolejka eksportu i NTP

### ✅ Dobrze zrobione

- Walidacja `NTP_SERVERS` przed zapisem pliku (zabezpieczenie przed injection)
- Testy jednostkowe dla skryptu `wlb-firstboot` (BATS)
- Restart `wlb-sluza-out.service` po montowaniu dysku

### ⚠️ Uwagi po weryfikacji

#### 1. Brak logowania błędów przy chrony (P2)

**Plik:** `ansible/roles/lab_config/files/wlb-firstboot`

**Status:** ⚠️ Częściowo trafna - to nie race condition, ale logowanie pomaga w debugowaniu

**Kontekst:** `chronyc reload sources >/dev/null 2>&1` ukrywa przyczynę niepowodzenia.

**Rekomendacja:**
```bash
if ! chronyc reload sources >/dev/null 2>&1; then
  log "chronyc reload failed, restarting chrony service"
  systemctl restart chrony
fi
```

---

#### 2. Restart śluzy przed zamontowaniem dysku (NIE DOTYCZY)

**Plik:** `ansible/roles/lab_config/files/wlb-firstboot`

**Status:** ❌ Nietrafna

**Wyjaśnienie:**
- `wlb-firstboot` działa w `runcmd`, czyli po module `mounts` w cloud-init
- Jednostka systemd ma `RequiresMountsFor=/workspace /sluza-out`
- systemd nie uruchomi usługi bez zamontowanych ścieżek

**Nie wymaga zmian.**

---

#### 3. Walidacja NTP_SERVERS - składnia chrony (P1)

**Plik:** `ansible/roles/lab_config/files/wlb-firstboot`

**Status:** ✅ Trafna (z innego powodu niż pierwotnie sądzono)

**Problem:** 
- Pierwotna uwaga dotyczyła portów, ale prawdziwy problem to składnia chrony
- Chrony używa `port N` jako osobnej dyrektywy, nie `host:port`
- Adres `host:123` przeszedłby walidację i zepsuł synchronizację
- IPv6 z `:` jest poprawne i musi być obsługiwane

**Rekomendacja:**
```bash
# Dopuszczaj tylko: hostname, IPv4 lub IPv6 (co najmniej 2 dwukropki)
# Odrzucaj host:port (pojedynczy dwukropek)
if [[ $s == *:*.* ]]; then
  # IPv6 z portem - odrzuć
  die "nieprawidłowy serwer NTP (IPv6 z portem nieobsługiwany): '$s'"
elif [[ $s =~ ^[A-Za-z0-9.-]+$ ]]; then
  # Hostname lub IPv4 - OK
  :  # pass
elif [[ $s =~ ^([0-9a-fA-F]*:[0-9a-fA-F]*:){2,}[0-9a-fA-F]*$ ]]; then
  # IPv6 - OK
  :  # pass
else
  die "nieprawidłowy serwer NTP: '$s'"
fi
```

**Testy:** Dodać testy bats dla:
- Poprawne: `ntp.example.com`, `10.0.0.1`, `2001:db8::1`
- Niepoprawne: `10.0.0.1:123`, `ntp.example.com:123`

---

#### 4. Brak testu faktycznej synchronizacji NTP (P3)

**Plik:** `tests/acceptance-remote.sh`

**Status:** ✅ Trafna

**Problem:** Test sprawdza tylko konfigurację (`chronyc sources`), nie synchronizację.

**Rekomendacja:**
```bash
# Testowy serwer SNTP na hoście (jak zaślepka SIEM)
# W teście akceptacyjnym:
expect_ok "chrony zsynchronizowany" bash -c 'chronyc sourcestats | grep -q "10\.0\.2\.2"'
```

**Uwaga:** To większa zmiana w teście integracyjnym (wymaga serwera SNTP w CI).
Może być zaimplementowane w tym PR lub jako osobne zgłoszenie.

---

## PR #1: Pipeline CI, testy jednostkowe i telemetria

### ✅ Dobrze zrobione

- Kompleksowe testy jednostkowe (pytest)
- FakeGitHub class do mockowania API
- Testy pokrywały różne scenariusze (infra failure, test failure, timeout)

### ⚠️ Uwagi po weryfikacji

#### 1. Walidacja schematu OTLP (P3)

**Plik:** `ci/ci_telemetry.py`

**Status:** ⚠️ Częściowo trafna

**Kontekst:** Dane OTLP są budowane wewnętrznie, a testy sprawdzają strukturę ręcznie.

**Rekomendacja:**
- Użyć `opentelemetry-proto` w testach do walidacji przez `json_format.Parse()`
- Tylko w testach, nie w działającym CI
- Dodać komentarz z linkiem do specyfikacji OTLP version

**Przykład:**
```python
# W testach:
from opentelemetry.proto.trace.v1 import trace_pb2
from google.protobuf import json_format


def test_otlp_schema():
    body, _ = build_traces(RUN, JOBS)
    # Oficjalna walidacja przeciwko protobuf
    json_format.Parse(json.dumps(body), trace_pb2.TracesData())
```

---

#### 2. Wyciek tokenów i haseł w logach (P2)

**Plik:** `ci/ci_telemetry.py`

**Status:** ⚠️ Częściowo trafna

**Kontekst:** 
- Do telemetrii trafiają tylko nazwy jobów i kroków, wyniki oraz czasy
- GitHub maskuje sekrety w outputach
- **Jedyna luka:** collector URL z credentials (`https://user:pass@otel:4318`) mógłby zostać wypisany w logu błędu

**Rekomendacja:**
```python
import re


def redact_sensitive(text):
    """Redaguj credentials z URL kolektora OTLP."""
    # Ukryj user:pass w URL
    return re.sub(r"(https?://)[^:@]+:[^@]+@", r"\1***:***@", text)


def export_otlp(endpoint, headers, data, post):
    try:
        post(endpoint, token, data, headers)
    except OSError as e:
        # Redaguj przed logowaniem
        problems.append(f"export failed: {redact_sensitive(str(e))}")
```

**Test:**
```python
def test_redact_collector_url():
    assert redact_sensitive("https://user:pass@otel:4318") == "https://***:***@otel:4318"
```

---

#### 3. Brak ponawiania eksportu (P1)

**Plik:** `ci/ci_telemetry.py`

**Status:** ✅ Trafna

**Problem:** Po błędzie sieci jest tylko ostrzeżenie, bez retry.

**Rekomendacja:**
```python
import time


def export_otlp(endpoint, headers, data, post):
    """Eksport OTLP z retry dla błędów sieci i 5xx."""
    max_retries = 3
    backoff = 1

    for attempt in range(max_retries):
        try:
            response = post(endpoint, token, data, headers)
            # Nie retry dla 4xx (poza 429)
            if 400 <= response.status < 500 and response.status != 429:
                problems.append(f"export failed (no retry): {response.status}")
                return
            return  # Success
        except (OSError, TimeoutError) as e:
            if attempt == max_retries - 1:
                problems.append(f"export failed after {max_retries} attempts: {e}")
                return
            time.sleep(backoff)
            backoff *= 2  # Exponential backoff: 1s, 2s, 4s
```

**Test:**
```python
def test_retry_on_network_error():
    """Sprawdź że eksport jest ponawiany przy błędzie sieci."""
    attempts = []

    def failing_post(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("network error")
        return {"status": 200}

    export_otlp("http://otel:4318", {}, {}, failing_post)
    assert len(attempts) == 3
```

---

#### 4. Domyślny adres OTLP (NIE DOTYCZY)

**Plik:** `ci/ci_telemetry.py`

**Status:** ❌ Nietrafna

**Wyjaśnienie:**
- Bez zmiennej środowiskowej `OTEL_EXPORTER_OTLP_ENDPOINT` eksport jest pomijany
- Telemetria trafia tylko do artefaktów (JSON w `tests/unit/`)
- Nie ma hardcoded defaulta w produkcji

**Nie wymaga zmian.**

---

## Podsumowanie

### Priorytet Wysoki (BLOCKERS):

| # | PR | Problem | Plik |
|---|----|---------|------|
| 1 | #1 | Brak ponawiania eksportu OTLP | `ci/ci_telemetry.py` |
| 2 | #28 | Walidacja NTP (IPv6, składnia chrony) | `ansible/roles/lab_config/files/wlb-firstboot` |

### Priorytet Średni:

| # | PR | Problem | Plik |
|---|----|---------|------|
| 3 | #1 | Wyciek credentials z URL kolektora | `ci/ci_telemetry.py` |
| 4 | #28 | Brak logowania błędów przy chrony | `ansible/roles/lab_config/files/wlb-firstboot` |

### Priorytet Niski:

| # | PR | Problem | Plik |
|---|----|---------|------|
| 5 | #1 | Oficjalna walidacja OTLP w testach | `tests/unit/test_ci_telemetry.py` |
| 6 | #28 | Test synchronizacji NTP | `tests/acceptance-remote.sh` |

---

## Pytania do autora

1. Czy telemetry zawiera jakieś dane osobowe badaczy?
2. Czy endpoint OTLP jest skonfigurowany z authentication?
3. Czy testy acceptance są uruchamiane w CI dla każdego commita?
4. Jaki jest oczekiwany czas retencji dla telemetrii CI?

---

**Decyzja:** ⚠️ **REQUEST CHANGES** - Wymaga poprawek przed merge (szczególnie P1: retry logic i walidacja NTP)
