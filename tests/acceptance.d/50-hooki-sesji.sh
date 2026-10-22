# shellcheck shell=bash
echo "== Hooki cyklu życia sesji badacza + emiter SIEM (#97) =="
expect_ok "Config hooka 80-wlb-session.py obecny i poprawny składniowo (#97)" \
  /opt/tljh/user/bin/python -m py_compile /opt/tljh/config/jupyterhub_config.d/80-wlb-session.py
expect_ok "Emiter sesji wykonywalny (#97)" test -x /opt/wlb/bin/wlb-session-log
/opt/wlb/bin/wlb-session-log start jupyter-tester1 10001 00000000000000000000000000000000 lab-test01
for _ in $(seq 1 10); do
  journalctl -t wlb-session 2>/dev/null | grep -q 'session_start user=jupyter-tester1 uid=10001 hub_session=0' && break
  sleep 1
done
expect_ok "Emiter sesji trafia do journala z tagiem wlb-session (#97)" \
  bash -c "journalctl -t wlb-session 2>/dev/null | grep -q 'session_start user=jupyter-tester1 uid=10001 hub_session=0'"
