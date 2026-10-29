"""Hook cyklu zycia sesji badacza (#98/#170): po restarcie huba czas trwania liczony
z zegara sciennego (odzyskany start_wall), NIGDY 0 udajace sesje zerowej dlugosci —
to samo klamstwo, ktoremu zapobiega konwencja pusty argument -> null."""

import json
import stat
import types

from conftest import REPO_ROOT

TEMPLATE = REPO_ROOT / "ansible/roles/tljh/templates/80-wlb-session.py.j2"


def load_hooks(state_dir, monkeypatch, *, now, monotonic=None):
    """Laduje szablon (czysty Python) z atrapa get_config, kontrolowanym czasem i
    przechwyceniem wywolan podprocesow. Zwraca (namespace, przechwycone_wywolania)."""
    monkeypatch.setenv("WLB_USAGE_STATE_DIR", str(state_dir))
    ns: dict = {}
    cfg = types.SimpleNamespace(Spawner=types.SimpleNamespace())
    ns["get_config"] = lambda: cfg
    code = compile(TEMPLATE.read_text(encoding="utf-8"), str(TEMPLATE), "exec")
    exec(code, ns)  # noqa: S102 — kontrolowany, lokalny szablon repo
    ns["time"] = types.SimpleNamespace(
        time=lambda: now,
        monotonic=(lambda: monotonic) if monotonic is not None else time_monotonic_unused,
    )
    calls: list[list[str]] = []
    ns["subprocess"] = types.SimpleNamespace(
        run=lambda args, **kw: (calls.append(list(args)), types.SimpleNamespace(returncode=0))[1]
    )
    return ns, calls


def time_monotonic_unused():  # pragma: no cover — wolane tylko gdy test zle ustawil monotonic
    raise AssertionError("time.monotonic nie powinno byc wolane w tej sciezce")


def _spawner(**attrs):
    s = types.SimpleNamespace(
        user=types.SimpleNamespace(name="tester1"),
        unit_name="jupyter-tester1.service",
        environment={"WLB_LAB_NAME": "lab-x"},
        log=types.SimpleNamespace(warning=lambda *a, **k: None),
    )
    for k, v in attrs.items():
        setattr(s, k, v)
    return s


def _call(calls, suffix, second=None):
    for c in calls:
        if c[0].endswith(suffix) and (second is None or (len(c) > 1 and c[1] == second)):
            return c
    return None


def test_restart_huba_duration_z_zegara_sciennego(tmp_path, monkeypatch):
    """Po restarcie huba spawner traci _wlb_start (monotonic), ale start_wall jest w stanie.
    Czas trwania musi byc liczony z zegara sciennego, NIE 0 (#170 finding 1)."""
    start_wall = 1_000_000
    now = start_wall + 3600
    (tmp_path / "jupyter-tester1.service.json").write_text(
        json.dumps({"session_id": "sess-1", "start_wall": start_wall, "lab_source": "spawner_env"}),
        encoding="utf-8",
    )
    ns, calls = load_hooks(tmp_path, monkeypatch, now=now)
    ns["wlb_post_stop_hook"](_spawner())  # BEZ _wlb_start / _wlb_start_wall (zginely z restartem)

    rec = _call(calls, "wlb-usage-record")
    assert rec is not None, "rekord uzycia powinien powstac (start_wall odzyskany ze stanu)"
    # argumenty: [prog, unit, sid, lab, start, stop, duration, lab_source]
    assert rec[2] == "sess-1"
    assert rec[4] == str(start_wall)
    assert rec[5] == str(now)
    assert rec[6] == "3600", "duration z zegara sciennego, nie 0"

    stop = _call(calls, "wlb-session-log", "stop")
    assert stop[-1] == "3600"


def test_normalna_sciezka_duration_z_monotonic(tmp_path, monkeypatch):
    """Gdy atrybuty spawnera istnieja, czas trwania liczony z zegara monotonicznego."""
    ns, calls = load_hooks(tmp_path, monkeypatch, now=2_000_000, monotonic=5000.0)
    ns["wlb_post_stop_hook"](_spawner(_wlb_start=4000.0, _wlb_start_wall=1_999_000.0, _wlb_session="sess-9"))

    assert _call(calls, "wlb-session-log", "stop")[-1] == "1000"  # 5000 - 4000
    assert _call(calls, "wlb-usage-record")[6] == "1000"


def test_brak_zrodel_czasu_duration_pusty_nie_zero(tmp_path, monkeypatch):
    """Brak atrybutow i brak start_wall w stanie -> pusty argument (null), NIE 0; rekord uzycia
    bez start_wall w ogole nie powstaje."""
    ns, calls = load_hooks(tmp_path, monkeypatch, now=2_000_000)
    ns["wlb_post_stop_hook"](_spawner())  # brak pliku stanu

    assert _call(calls, "wlb-session-log", "stop")[-1] == ""  # null, nie "0"
    assert _call(calls, "wlb-usage-record") is None


def test_pre_spawn_interrupted_uzywa_lab_ze_stanu(tmp_path, monkeypatch):
    """Osierocona sesja domykana jest z lab/lab_source z ZAPISANEGO stanu, nie z biezacego
    spawnu — inaczej rekord starej sesji trafialby pod Lab nowej (#170 finding 3)."""
    (tmp_path / "jupyter-tester1.service.json").write_text(
        json.dumps({"session_id": "sess-OLD", "start_wall": 1_000_000,
                    "lab": "lab-OLD", "lab_source": "spawner_env"}),
        encoding="utf-8",
    )
    ns, calls = load_hooks(tmp_path, monkeypatch, now=2_000_000, monotonic=1234.0)
    ns["wlb_pre_spawn_hook"](_spawner(environment={"WLB_LAB_NAME": "lab-NEW"}))  # INNY Lab niz stary

    interrupted = _call(calls, "wlb-usage-record")
    assert interrupted is not None
    assert interrupted[2] == "sess-OLD"
    assert interrupted[3] == "lab-OLD", "lab osieroconej sesji ze stanu, nie biezacej"
    assert interrupted[7] == "interrupted:spawner_env"


def test_write_state_katalog_0700_plik_0600_i_zapisuje_lab(tmp_path, monkeypatch):
    """Gdy katalog stanu nie istnieje, hook tworzy go 0700 i plik 0600 (nie 0755/0644 z umaski),
    a stan zawiera lab do poprawnej atrybucji po restarcie (#170 findings 3+4)."""
    state_dir = tmp_path / "run" / "sessions"  # nie istnieje
    ns, _ = load_hooks(state_dir, monkeypatch, now=1_000_000, monotonic=1.0)
    assert not state_dir.exists()

    ns["_wlb_write_state"](_spawner(), "jupyter-tester1.service",
                           {"session_id": "s", "start_wall": 1, "lab": "lab-x", "lab_source": "spawner_env"})

    path = state_dir / "jupyter-tester1.service.json"
    assert path.exists()
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["lab"] == "lab-x"
