"""Hook cyklu zycia sesji badacza (#98/#170): po restarcie huba czas trwania liczony
z zegara sciennego (odzyskany start_wall), NIGDY 0 udajace sesje zerowej dlugosci —
to samo klamstwo, ktoremu zapobiega konwencja pusty argument -> null."""

import json
import os
import stat
import types

import pytest
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
        json.dumps({"session_id": "sess-OLD", "start_wall": 1_000_000, "lab": "lab-OLD", "lab_source": "spawner_env"}),
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

    ns["_wlb_write_state"](
        _spawner(),
        "jupyter-tester1.service",
        {"session_id": "s", "start_wall": 1, "lab": "lab-x", "lab_source": "spawner_env"},
    )

    path = state_dir / "jupyter-tester1.service.json"
    assert path.exists()
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["lab"] == "lab-x"


@pytest.mark.parametrize("legacy", [False, True])
def test_post_stop_lab_z_pasujacego_stanu_nie_z_nowej_konfiguracji(tmp_path, monkeypatch, legacy):
    state = {"session_id": "sess-OLD", "start_wall": 1_000_000, "lab_source": "spawner_env"}
    if not legacy:
        state["lab"] = "lab-OLD"
    (tmp_path / "jupyter-tester1.service.json").write_text(json.dumps(state), encoding="utf-8")
    ns, calls = load_hooks(tmp_path, monkeypatch, now=1_003_600)

    ns["wlb_post_stop_hook"](_spawner(environment={"WLB_LAB_NAME": "lab-NEW"}))

    expected_lab = "" if legacy else "lab-OLD"
    assert _call(calls, "wlb-usage-record")[3] == expected_lab
    assert _call(calls, "wlb-usage-record")[7] == "spawner_env"
    assert _call(calls, "wlb-session-log", "stop")[5] == expected_lab


def test_post_stop_nie_bierze_lab_z_innej_sesji(tmp_path, monkeypatch):
    (tmp_path / "jupyter-tester1.service.json").write_text(
        json.dumps({"session_id": "other", "start_wall": 1, "lab": "other-lab", "lab_source": "hub_env"}),
        encoding="utf-8",
    )
    ns, calls = load_hooks(tmp_path, monkeypatch, now=2_000_000, monotonic=5000.0)
    ns["wlb_post_stop_hook"](_spawner(_wlb_start=4000.0, _wlb_start_wall=1_999_000.0, _wlb_session="current"))

    assert _call(calls, "wlb-usage-record")[3] == "lab-x"
    assert _call(calls, "wlb-usage-record")[7] == "spawner_env"


def test_pre_spawn_stary_format_nie_pożycza_lab_nowej_sesji(tmp_path, monkeypatch):
    (tmp_path / "jupyter-tester1.service.json").write_text(
        json.dumps({"session_id": "old", "start_wall": 1, "lab_source": "hub_env"}), encoding="utf-8"
    )
    ns, calls = load_hooks(tmp_path, monkeypatch, now=100, monotonic=10.0)
    ns["wlb_pre_spawn_hook"](_spawner())

    assert _call(calls, "wlb-usage-record")[3] == ""
    assert _call(calls, "wlb-usage-record")[7] == "interrupted:hub_env"
    saved = json.loads((tmp_path / "jupyter-tester1.service.json").read_text())
    assert saved["lab"] == "lab-x"
    assert saved["session_id"] != "old"


@pytest.mark.parametrize("stale_tmp", ["file", "symlink"])
def test_write_state_naprawia_prawa_i_nie_uzywa_starego_tmp(tmp_path, monkeypatch, stale_tmp):
    state_dir = tmp_path / "sessions"
    state_dir.mkdir()
    state_dir.chmod(0o755)
    old_tmp = state_dir / "jupyter-tester1.service.json.tmp"
    target = tmp_path / "unrelated"
    target.write_text("preserve", encoding="utf-8")
    if stale_tmp == "symlink":
        old_tmp.symlink_to(target)
    else:
        old_tmp.write_text("old", encoding="utf-8")
        old_tmp.chmod(0o644)
    ns, _ = load_hooks(state_dir, monkeypatch, now=100)
    saved = {"session_id": "new", "start_wall": 1, "lab": "lab-x", "lab_source": "spawner_env"}
    previous_umask = os.umask(0)
    try:
        ns["_wlb_write_state"](_spawner(), "jupyter-tester1.service", saved)
    finally:
        os.umask(previous_umask)

    path = state_dir / "jupyter-tester1.service.json"
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.is_symlink()
    assert json.loads(path.read_text()) == saved
    assert target.read_text() == "preserve"


@pytest.mark.parametrize("failure", ["mkdir", "chmod", "replace"])
def test_write_state_blad_nie_blokuje_i_zachowuje_poprzedni_stan(tmp_path, monkeypatch, failure):
    path = tmp_path / "jupyter-tester1.service.json"
    path.write_text('{"session_id": "old"}', encoding="utf-8")
    ns, _ = load_hooks(tmp_path, monkeypatch, now=100)
    warnings = []
    spawner = _spawner(log=types.SimpleNamespace(warning=lambda *args: warnings.append(args)))

    def fail(*args, **kwargs):
        raise OSError("simulated storage failure")

    attribute = "makedirs" if failure == "mkdir" else failure
    with monkeypatch.context() as patch:
        patch.setattr(ns["os"], attribute, fail)
        ns["_wlb_write_state"](spawner, "jupyter-tester1.service", {"session_id": "new"})

    assert json.loads(path.read_text()) == {"session_id": "old"}
    assert warnings
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
