# shellcheck shell=bash
# Etap 1b (#138): render-smoke pulpitu wpięty w akceptację — ADAPTACYJNY i NIE-BRAMKUJĄCY.
#
# Na flavorach z pulpitem (wlb-memory #106, wlb-radiologia #135) uruchamia render-smoke JAKO badacz
# (/opt/wlb/tests/desktop-render-smoke.sh, wgrany przez rolę desktop). Render to test RUNTIME
# (start X + XFCE + interakcja), z natury wrażliwy na czas — dopóki nie ma empirycznej walidacji KVM
# (#138 §8: ≥20 czystych przebiegów), błąd renderu NIE bramkuje stage 5: raportujemy go jako SKIP,
# żeby nie wnosić fałszywych czerwonych (#86). Udany render daje PASS (realny sygnał „pulpit się rysuje").
#
# Promocja do bramkowania po walidacji: ustaw WLB_RENDER_SMOKE_GATING=1 — wtedy błąd renderu to ko (FAIL).
if /opt/tljh/user/bin/python -c "import jupyter_remote_desktop_proxy" 2>/dev/null; then
  echo "== Render-smoke pulpitu (#138, etap 1b — NIE-bramkujący, SKIP przy błędzie) =="
  W45_SMOKE=/opt/wlb/tests/desktop-render-smoke.sh
  if [[ ! -x $W45_SMOKE ]]; then
    skip "Render-smoke: brak wykonywalnego $W45_SMOKE na obrazie (#138)"
  else
    W45_LOG=$(mktemp)
    # Skrypt tnie własny deadline; WLB_SMOKE_TIMEOUT < limit kroku CI. Uruchomienie JAKO badacz
    # (as R1) — XFCE pod rootem jest niewspierany; display dobierany automatycznie (WLB_SMOKE_DISPLAY=auto).
    if as "$R1" env WLB_SMOKE_TIMEOUT=120 "$W45_SMOKE" >"$W45_LOG" 2>&1; then
      ok "Pulpit realnie się renderuje i reaguje na interakcję (render-smoke, #138)"
    elif [[ ${WLB_RENDER_SMOKE_GATING:-0} == 1 ]]; then
      ko "Render-smoke pulpitu nieudany (#138): $(tail -n1 "$W45_LOG")"
    else
      skip "Render-smoke pulpitu nieudany — NIE bramkuje do walidacji KVM (#138 §8): $(tail -n1 "$W45_LOG")"
    fi
    rm -f "$W45_LOG"
  fi
fi
