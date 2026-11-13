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
with open(result, "w", encoding="utf-8") as fh:
    fh.write("scratch=%s\n" % scratch)
    fh.write("scratch_uid=%s\n" % scratch_uid)
    fh.write("xauth=%s\n" % " ".join(" ".join(c) for c in calls))
PY
expect_ok "pre_spawn tworzy scratch per-unit na tmpfs i ustawia TMPDIR sesji (#318)" \
  test "$(sed -n 's/^scratch=//p' "$W50_RESULT")" = "$W50_SCRATCH"
expect_ok "scratch należy do UID badacza (10000-59999, #318)" \
  test "$(sed -n 's/^scratch_uid=//p' "$W50_RESULT")" = "$W50_UID"
expect_ok "post_stop usuwa scratch w całości (katalog z podkatalogiem, #318)" test ! -e "$W50_SCRATCH"
expect_ok "Plik-świadek w /workspace przeżywa sprzatanie (deny-lista, #318)" \
  test -f "$W50_HOME/wlb-318-witness"
expect_ok "Kolejka .wlb-export-queue nietknięta (deny-lista, #318)" \
  test -f /workspace/.wlb-export-queue/wlb-318-witness
expect_ok "Ścieżka spoza allowlisty nietknięta (test negatywny, #318)" \
  test -f /tmp/wlb-318-poza-allowlista/marker

# Reaping artefaktów display-scoped — tylko na pulpicie (xauth z roli desktop) i dla UID badacza.
if [ -x /opt/wlb/desktop/wlb-desktop-xstartup ] && command -v xauth >/dev/null 2>&1; then
  mkdir -p /tmp/.X11-unix "$W50_HOME/.vnc"
  : >/tmp/.X11-unix/X77
  : >/tmp/.X77-lock
  : >"$W50_HOME/.vnc/wlb-318.pid"
  : >"$W50_HOME/.vnc/wlb-318-other.txt"
  chown "jupyter-$R2" /tmp/.X11-unix/X77 /tmp/.X77-lock "$W50_HOME/.vnc/wlb-318.pid" \
    "$W50_HOME/.vnc/wlb-318-other.txt"
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
  expect_ok "Reaping display: plik .vnc/*.pid usunięty (#318)" test ! -e "$W50_HOME/.vnc/wlb-318.pid"
  expect_ok "Reaping display: plik .vnc spoza wzorca nietknięty (#318)" \
    test -f "$W50_HOME/.vnc/wlb-318-other.txt"
  expect_ok "xauth: wpis :77 usunięty, plik .Xauthority zachowany (#318)" \
    bash -c 'test -f /workspace/.Xauthority && ! xauth -f /workspace/.Xauthority list :77 | grep -q .'
  rm -f /workspace/.Xauthority "$W50_HOME/.vnc/wlb-318-other.txt"
else
  skip "Reaping display-scoped (#318): brak pulpitu/xauth — sprawdzone testami jednostkowymi"
fi

rm -f "$W50_HOME/wlb-318-witness" /workspace/.wlb-export-queue/wlb-318-witness
rm -rf /tmp/wlb-318-poza-allowlista "$W50_RESULT"
