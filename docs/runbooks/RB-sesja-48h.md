# RB: wydłużenie limitu sesji do 48 h (#78, §9.5)

**Odniesienia:** #78 (decyzja), §9.5 Regulaminu (limit sesji / re-auth), group_vars `tljh_max_session_seconds`, `wlb-firstboot` (opcja `MAX_SESSION_HOURS`). **Zakres:** `wlb-golden-image`.

Domyślny limit sesji badacza to **12 h**: po tym culler zatrzymuje serwer notebooków, a ciasteczko huba i tokeny OAuth wygasają (ponowne logowanie). Product Owner zgodził się wydłużać go **do maks. 48 h na wniosek badacza**, per-Laboratorium (cała VM). 48 h = dłuższe okno re-auth → **świadome odstępstwo §9.5** (odnotować w rejestrze odstępstw).

> **Zastrzeżenie dla badacza:** 48 h usuwa limit sesji jako przyczynę utraty, ale **nie** czyni obliczenia odpornym na awarię — stan w pamięci ginie przy reboocie/wymianie obrazu/awarii hosta. Checkpoint do `/workspace` pozostaje konieczny (patrz strona pomocy badacza).

## A. Nowa VM — przez build/deploy (zalecane)

W `/etc/wlb/lab.env` (cloud-init) ustaw przed pierwszym startem:

```sh
MAX_SESSION_HOURS=48        # 1–48; puste = domyślne 12 h
```

`wlb-firstboot` spójnie ustawi `services.cull.max_age` oraz TTL ciasteczka/tokenu (plik `11-wlb-session.py` nadpisujący `10-wlb.py`). Zero ręcznej edycji.

## B. DZIAŁAJĄCA VM — podmiana bez przerywania badań

Serwer badacza to niezależna jednostka `jupyter-<login>.service`, więc **restart huba NIE zabija liczącego jądra** — badania w toku nie są przerywane. Wszystko przez SSH z `sudo` (konto administratora platformy; Administrator Klienta nie ma sudo).

Dalej `N` oznacza docelową długość sesji w godzinach (1–48); przykład dla 48 h: `N=48`.

**1. Backup:**
```sh
sudo cp /opt/tljh/config/config.yaml{,.bak-$(date +%F)}
```

**2. Culler na N godzin:**
```sh
N=48                       # 1–48; przykład dla 48 h
sudo /opt/tljh/hub/bin/tljh-config set services.cull.max_age $((N * 3600))
```

**3. TTL ciasteczka/tokenu dla N godzin** — utwórz plik nadpisujący `10-wlb.py` (ten sam, który generuje build):
```sh
N=48                       # ustaw tak samo jak w kroku 2
sudo tee /opt/tljh/config/jupyterhub_config.d/11-wlb-session.py >/dev/null <<PY
# Ręczne wydłużenie sesji do ${N} h (#78, §9.5). Nadpisuje 10-wlb.py (wyższy numer = ładowane później).
c = get_config()  # noqa: F821
c.JupyterHub.cookie_max_age_days = ${N} / 24
c.JupyterHub.oauth_token_expires_in = ${N} * 3600
PY
```

**4. Przeładuj huba** (nie zabija `jupyter-<login>.service`):
```sh
sudo /opt/tljh/hub/bin/tljh-config reload hub
```

**5. Weryfikacja:**
```sh
sudo /opt/tljh/hub/bin/tljh-config show | grep -A3 cull     # max_age = N*3600 (dla N=48: 172800)
ls /opt/tljh/config/jupyterhub_config.d/11-wlb-session.py
```

## Rollback
```sh
sudo /opt/tljh/hub/bin/tljh-config set services.cull.max_age 43200
sudo rm -f /opt/tljh/config/jupyterhub_config.d/11-wlb-session.py
sudo /opt/tljh/hub/bin/tljh-config reload hub
```

## Uwagi
- **Uwaga:** `shutdown_on_logout=True` — po wygaśnięciu tokenu badacz ma **zalogować się ponownie**, a **nie** klikać „Wyloguj"; wylogowanie zatrzymuje serwer notebooków (`jupyter-<login>.service`) i przy 48-godzinnym liczeniu grozi utratą niezapisanej pracy.
- Zmiana na działającej VM jest **nietrwała przy wymianie obrazu** (nowy dysk systemowy) — docelowo użyj wariantu A (`MAX_SESSION_HOURS` w lab.env), żeby przeżyła aktualizację.
- Aktualny token badacza mógł zostać wydany z 12 h TTL — pełne 48 h obowiązuje od następnego logowania; **liczące jądro i tak działa dalej** (to culler, nie token, kończył sesję).
- Przy kilku kontach uNN na jednej VM wydłużenie obejmuje **wszystkie** konta na tej VM (`cull.max_age` jest globalny dla huba).

## Odstępstwo §9.5 do odnotowania w rejestrze

Wydłużenie limitu sesji poza 12 h jest świadomym odstępstwem od §9.5 Regulaminu. Wpis należy
odnotować w rejestrze decyzji i odstępstw (ADR, [docs/adr/](../adr/),
[#14](https://github.com/xWuWux/wlb-golden-image/issues/14)) i podlinkować do decyzji
[#78](https://github.com/xWuWux/wlb-golden-image/issues/78), aby uzasadnienie nie zginęło.
