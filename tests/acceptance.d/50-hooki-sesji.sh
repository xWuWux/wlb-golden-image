# shellcheck shell=bash
echo "== Hooki cyklu życia sesji badacza + emiter SIEM (#97) =="
expect_ok "Config hooka 80-wlb-session.py obecny i poprawny składniowo (#97)" \
  /opt/tljh/user/bin/python -m py_compile /opt/tljh/config/jupyterhub_config.d/80-wlb-session.py
expect_ok "Emiter sesji wykonywalny (#97)" test -x /opt/wlb/bin/wlb-session-log
/opt/wlb/bin/wlb-session-log start jupyter-u01 10001 00000000000000000000000000000000 lab-test01
for _ in $(seq 1 10); do
  journalctl -t wlb-session 2>/dev/null | grep -q 'session_start user=jupyter-u01 uid=10001 hub_session=0' && break
  sleep 1
done
expect_ok "Emiter sesji trafia do journala z tagiem wlb-session (#97)" \
  bash -c "journalctl -t wlb-session 2>/dev/null | grep -q 'session_start user=jupyter-u01 uid=10001 hub_session=0'"

# #318: sprzatanie scratcha sesji w post_stop_hook. Hook wywołujemy z atrapą spawnera (nie ruszamy
# realnej sesji u02) — prawdziwe ścieżki VM: tmpfs /run, trwały /workspace i deny-lista.
W50_HOME=$(getent passwd "jupyter-$R2" | cut -d: -f6)
W50_UID=$(id -u "jupyter-$R2")
W50_UNIT="jupyter-$R2-318test.service"
W50_SCRATCH="/run/wlb/scratch/$W50_UNIT"
mkdir -p "$W50_HOME" /workspace/.wlb-export-queue /tmp/wlb-318-poza-allowlista
printf 'witness\n' >"$W50_HOME/wlb-318-witness"
printf 'witness\n' >/workspace/.wlb-export-queue/wlb-318-witness
printf 'marker\n' >/tmp/wlb-318-poza-allowlista/marker
rm -rf "$W50_SCRATCH"
W50_RESULT=/tmp/wlb-318-result
/opt/tljh/user/bin/python - "$W50_RESULT" "$R2" "$W50_UNIT" <<'PY'
import os
import subprocess as real_subprocess
import sys
import types

result, user, unit = sys.argv[1:4]
ns: dict = {}
cfg = types.SimpleNamespace(Spawner=types.SimpleNamespace())
ns["get_config"] = lambda: cfg
exec(compile(open("/opt/tljh/config/jupyterhub_config.d/80-wlb-session.py").read(),
             "80-wlb-session.py", "exec"), ns)  # noqa: S102 — renderowany szablon z obrazu
calls = []


def run(args, **kw):
    calls.append(list(args))
    if args and args[0] == "xauth":  # xauth musi wykonać się naprawdę; telemetrię stubujemy
        return types.SimpleNamespace(returncode=real_subprocess.run(args, **kw).returncode)
    return types.SimpleNamespace(returncode=0)


ns["subprocess"] = types.SimpleNamespace(run=run)
warn = []
spawner = types.SimpleNamespace(
    user=types.SimpleNamespace(name=user),
    unit_name=unit,
    environment={},
    log=types.SimpleNamespace(warning=lambda *a, **k: warn.append(a)),
)
ns["wlb_pre_spawn_hook"](spawner)
scratch = spawner.environment.get("TMPDIR", "")
scratch_uid = ""
if scratch and os.path.isdir(scratch):
    scratch_uid = str(os.stat(scratch).st_uid)
    os.makedirs(os.path.join(scratch, "sub"), exist_ok=True)
    with open(os.path.join(scratch, "sub", "plik.tmp"), "w", encoding="utf-8") as fh:
        fh.write("x")
ns["wlb_post_stop_hook"](spawner)

# Test osieroconej sesji: plik stanu z poprzedniej sesji musi zostać domknięty jako interrupted
import json
stale_unit = unit + "-stale"
stale_file = os.path.join(ns["_WLB_STATE_DIR"], stale_unit + ".json")
os.makedirs(ns["_WLB_STATE_DIR"], exist_ok=True)
with open(stale_file, "w", encoding="utf-8") as fh:
    json.dump({"session_id": "sess-stale-97", "start_wall": 123456, "lab_source": "spawner_env"}, fh)
stale_spawner = types.SimpleNamespace(
    user=types.SimpleNamespace(name=user),
    unit_name=stale_unit,
    environment={"WLB_LAB_NAME": "lab-test01"},
    log=types.SimpleNamespace(warning=lambda *a, **k: warn.append(a)),
)
ns["wlb_pre_spawn_hook"](stale_spawner)
interrupted_call = [c for c in calls if c and c[0].endswith("wlb-usage-record") and "interrupted:spawner_env" in c]
ns["wlb_post_stop_hook"](stale_spawner)

with open(result, "w", encoding="utf-8") as fh:
    fh.write("scratch=%s\n" % scratch)
    fh.write("scratch_uid=%s\n" % scratch_uid)
    fh.write("xauth=%s\n" % " ".join(" ".join(c) for c in calls))
    fh.write("interrupted=%s\n" % ("ok" if interrupted_call else "none"))
PY
expect_ok "pre_spawn tworzy scratch per-unit na tmpfs i ustawia TMPDIR sesji (#318)" \
  test "$(sed -n 's/^scratch=//p' "$W50_RESULT")" = "$W50_SCRATCH"
expect_ok "scratch należy do UID badacza (10000-59999, #318)" \
  test "$(sed -n 's/^scratch_uid=//p' "$W50_RESULT")" = "$W50_UID"
expect_ok "pre_spawn domyka osieroconą sesję jako interrupted (#97, #98)" \
  test "$(sed -n 's/^interrupted=//p' "$W50_RESULT")" = "ok"
expect_ok "post_stop usuwa scratch w całości (katalog z podkatalogiem, #318)" test ! -e "$W50_SCRATCH"
expect_ok "Plik-świadek w /workspace przeżywa sprzatanie (deny-lista, #318)" \
  test -f "$W50_HOME/wlb-318-witness"
expect_ok "Kolejka .wlb-export-queue nietknięta (deny-lista, #318)" \
  test -f /workspace/.wlb-export-queue/wlb-318-witness
expect_ok "Ścieżka spoza allowlisty nietknięta (test negatywny, #318)" \
  test -f /tmp/wlb-318-poza-allowlista/marker

# Reaping artefaktów X/VNC UID-scoped — tylko na pulpicie (xauth z roli desktop) i dla UID badacza.
# TigerVNC: usuwamy wyłącznie <host>:<d>.pid/.log skorelowane z DISPLAY; dane badacza w ~/.vnc zostają.
if [ -x /opt/wlb/desktop/wlb-desktop-xstartup ] && command -v xauth >/dev/null 2>&1; then
  mkdir -p /tmp/.X11-unix "$W50_HOME/.vnc"
  : >/tmp/.X11-unix/X77
  : >/tmp/.X77-lock
  : >"$W50_HOME/.vnc/lab-test01:77.pid"
  : >"$W50_HOME/.vnc/lab-test01:77.log"
  : >"$W50_HOME/.vnc/keepme.log"
  : >"$W50_HOME/.vnc/wlb-318-other.txt"
  chown "jupyter-$R2" /tmp/.X11-unix/X77 /tmp/.X77-lock "$W50_HOME/.vnc/lab-test01:77.pid" \
    "$W50_HOME/.vnc/lab-test01:77.log" "$W50_HOME/.vnc/keepme.log" "$W50_HOME/.vnc/wlb-318-other.txt"
  xauth -f /workspace/.Xauthority add :77 MIT-MAGIC-COOKIE-1 0123456789abcdef0123456789abcdef
  /opt/tljh/user/bin/python - "$R2" "$W50_UNIT" <<'PY'
import subprocess as real_subprocess
import sys
import types

user, unit = sys.argv[1:3]
ns: dict = {}
cfg = types.SimpleNamespace(Spawner=types.SimpleNamespace())
ns["get_config"] = lambda: cfg
exec(compile(open("/opt/tljh/config/jupyterhub_config.d/80-wlb-session.py").read(),
             "80-wlb-session.py", "exec"), ns)  # noqa: S102


def run(args, **kw):
    if args and args[0] == "xauth":
        return types.SimpleNamespace(returncode=real_subprocess.run(args, **kw).returncode)
    return types.SimpleNamespace(returncode=0)


ns["subprocess"] = types.SimpleNamespace(run=run)
spawner = types.SimpleNamespace(
    user=types.SimpleNamespace(name=user),
    unit_name=unit,
    environment={},
    log=types.SimpleNamespace(warning=lambda *a, **k: None),
)
ns["wlb_post_stop_hook"](spawner)
PY
  expect_ok "Reaping display: gniazdo X usunięte dla zwalnianego UID (#318)" test ! -e /tmp/.X11-unix/X77
  expect_ok "Reaping display: lock X usunięty (#318)" test ! -e /tmp/.X77-lock
  expect_ok "Reaping UID-scoped: <host>:77.pid/.log usunięte dla DISPLAY 77 (#318)" \
    test ! -e "$W50_HOME/.vnc/lab-test01:77.pid" -a ! -e "$W50_HOME/.vnc/lab-test01:77.log"
  expect_ok "Reaping UID-scoped: plik badacza keepme.log przeżył (nie blanket *.log, #318)" \
    test -f "$W50_HOME/.vnc/keepme.log"
  expect_ok "Reaping UID-scoped: plik .vnc spoza wzorca DISPLAY nietknięty (#318)" \
    test -f "$W50_HOME/.vnc/wlb-318-other.txt"
  expect_ok "xauth: wpis :77 usunięty, plik .Xauthority zachowany (#318)" \
    bash -c 'test -f /workspace/.Xauthority && ! xauth -f /workspace/.Xauthority list :77 | grep -q .'
  rm -f /workspace/.Xauthority "$W50_HOME/.vnc/keepme.log" "$W50_HOME/.vnc/wlb-318-other.txt"
else
  skip "Reaping display-scoped (#318): brak pulpitu/xauth — sprawdzone testami jednostkowymi"
fi

# --- Pełny E2E cykl życia z realnym Hubem (#97, #318) ---
# Weryfikacja że realny JupyterHub / SystemdSpawner wykonuje wlb_pre_spawn_hook i wlb_post_stop_hook
# w pełnym cyklu życia serwera badacza: spawn -> TMPDIR i scratch 0700 -> stop przez API Huba
# -> usunięcie scratcha i stanów -> skorelowany session_stop w journald -> ponowny spawn z nowym UUID.
if systemctl is-active --quiet "jupyter-$R2"; then
  W50_REAL_UNIT="jupyter-$R2.service"
  W50_REAL_SCRATCH="/run/wlb/scratch/$W50_REAL_UNIT"
  W50_REAL_STATE="/run/wlb/usage/sessions/$W50_REAL_UNIT.json"

  expect_ok "Realny Hub: scratch sesji na tmpfs obecny dla jupyter-$R2 (#97, #318)" test -d "$W50_REAL_SCRATCH"
  expect_ok "Realny Hub: scratch ma tryb 0700 (#97, #318)" \
    bash -c "[ \"\$(stat -c %a \"$W50_REAL_SCRATCH\")\" = 700 ]"
  expect_ok "Realny Hub: scratch należy do badacza $R2 (#97, #318)" \
    bash -c "[ \"\$(stat -c %u \"$W50_REAL_SCRATCH\")\" = \"$W50_UID\" ]"
  expect_ok "Realny Hub: plik stanu sesji obecny (#97, #98)" test -s "$W50_REAL_STATE"

  W50_E2E_SID1=$(sed -n 's/.*"session_id": *"\([^"]*\)".*/\1/p' "$W50_REAL_STATE")
  expect_ok "Realny Hub: session_id w stanie sesji jest niepusty (#97)" test -n "$W50_E2E_SID1"
  expect_ok "Realny Hub: session_start wyemitowany do journald z SID1 (#97)" \
    bash -c "journalctl -t wlb-session 2>/dev/null | grep -q 'session_start user=jupyter-$R2 .*hub_session=$W50_E2E_SID1'"

  # Zapisujemy plik-marker w scratchu badacza, aby dowieść że zostanie skasowany przez post_stop_hook
  touch "$W50_REAL_SCRATCH/e2e-marker.tmp"
  chown "jupyter-$R2" "$W50_REAL_SCRATCH/e2e-marker.tmp"

  expect_ok "Realny Hub: zatrzymanie serwera przez API Huba (hub_stop $R2) (#97)" \
    hub_stop "$R2"
  expect_fail "Realny Hub: jednostka systemd zatrzymana (#97)" \
    systemctl is-active --quiet "jupyter-$R2"
  expect_ok "Realny Hub: scratch sesji całkowicie usunięty po stopie (#97, #318)" \
    test ! -e "$W50_REAL_SCRATCH"
  expect_ok "Realny Hub: plik stanu sesji usunięty po stopie (#97)" \
    test ! -e "$W50_REAL_STATE"

  for _ in $(seq 1 15); do
    journalctl -t wlb-session 2>/dev/null | grep -qE "session_stop user=jupyter-$R2 .*hub_session=$W50_E2E_SID1 duration=[0-9]+" && break
    sleep 1
  done
  expect_ok "Realny Hub: session_stop w journald ze skorelowanym SID1 i czasem trwania (#97)" \
    bash -c "journalctl -t wlb-session 2>/dev/null | grep -qE 'session_stop user=jupyter-$R2 .*hub_session=$W50_E2E_SID1 duration=[0-9]+'"

  # Ponowny spawn serwera przez Hub — weryfikacja czystego startu nowej sesji z nowym UUID
  expect_ok "Realny Hub: ponowny spawn serwera $R2 (#97)" \
    hub_spawn "$R2"
  expect_ok "Realny Hub: jednostka systemd ponownie aktywna (#97)" \
    systemctl is-active --quiet "jupyter-$R2"
  expect_ok "Realny Hub: nowy scratch sesji utworzony (#97, #318)" \
    test -d "$W50_REAL_SCRATCH"

  W50_E2E_SID2=$(sed -n 's/.*"session_id": *"\([^"]*\)".*/\1/p' "$W50_REAL_STATE")
  expect_ok "Realny Hub: nowy session_id jest różny od poprzedniego (#97)" \
    test -n "$W50_E2E_SID2" -a "$W50_E2E_SID2" != "$W50_E2E_SID1"

  for _ in $(seq 1 15); do
    journalctl -t wlb-session 2>/dev/null | grep -q "session_start user=jupyter-$R2 .*hub_session=$W50_E2E_SID2" && break
    sleep 1
  done
  expect_ok "Realny Hub: session_start wyemitowany dla nowego SID2 (#97)" \
    bash -c "journalctl -t wlb-session 2>/dev/null | grep -q 'session_start user=jupyter-$R2 .*hub_session=$W50_E2E_SID2'"
else
  skip "Realny Hub E2E (#97): serwer jupyter-$R2 nie jest aktywny"
fi

rm -f "$W50_HOME/wlb-318-witness" /workspace/.wlb-export-queue/wlb-318-witness
rm -rf /tmp/wlb-318-poza-allowlista "$W50_RESULT"
