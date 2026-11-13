"""Hook cyklu zycia sesji badacza (#98/#170): po restarcie huba czas trwania liczony
z zegara sciennego (odzyskany start_wall), NIGDY 0 udajace sesje zerowej dlugosci —
to samo klamstwo, ktoremu zapobiega konwencja pusty argument -> null."""

import json
import os
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


def _fake_pwd(home, uid=None):
    uid = os.getuid() if uid is None else uid
    return types.SimpleNamespace(
        getpwnam=lambda user: types.SimpleNamespace(pw_uid=uid, pw_gid=os.getgid(), pw_dir=home)
    )


def _allow_any_uid(ns):
    ns["_WLB_UID_MIN"] = 0
    ns["_WLB_UID_MAX"] = 2**31 - 1


def test_pre_spawn_tworzy_scratch_i_ustawia_TMPDIR(tmp_path, monkeypatch):
    """#318: pre_spawn tworzy dedykowany scratch per-unit na tmpfs i wstawia TMPDIR do środowiska."""
    scratch_root = tmp_path / "scratch"
    monkeypatch.setenv("WLB_SCRATCH_ROOT", str(scratch_root))
    ns, _ = load_hooks(tmp_path / "state", monkeypatch, now=1, monotonic=0.0)
    ns["pwd"] = _fake_pwd(str(tmp_path / "home"))
    _allow_any_uid(ns)
    spawner = _spawner()

    ns["wlb_pre_spawn_hook"](spawner)

    expected = str(scratch_root / "jupyter-tester1.service")
    assert spawner.environment["TMPDIR"] == expected
    assert os.path.isdir(expected)
    assert (os.stat(expected).st_mode & 0o777) == 0o700


def test_post_stop_usuwa_scratch_rekurencyjnie(tmp_path, monkeypatch):
    """#318: post_stop usuwa scratch w całości (katalog + podkatalogi), nie tylko pliki."""
    scratch_root = tmp_path / "scratch"
    monkeypatch.setenv("WLB_SCRATCH_ROOT", str(scratch_root))
    ns, _ = load_hooks(tmp_path / "state", monkeypatch, now=2)
    ns["pwd"] = _fake_pwd(str(tmp_path / "home"))
    _allow_any_uid(ns)
    scratch = scratch_root / "jupyter-tester1.service"
    (scratch / "sub").mkdir(parents=True)
    (scratch / "sub" / "plik.tmp").write_text("x", encoding="utf-8")

    ns["wlb_post_stop_hook"](_spawner())

    assert not scratch.exists()


def test_scratch_nie_powstaje_gdy_sciezka_jest_z_denylisty(tmp_path, monkeypatch):
    """#318: /workspace jest bezwzględnie zabronione — scratch nie może tam powstać."""
    monkeypatch.setenv("WLB_SCRATCH_ROOT", "/workspace")
    ns, _ = load_hooks(tmp_path / "state", monkeypatch, now=3, monotonic=0.0)
    ns["pwd"] = _fake_pwd(str(tmp_path / "home"))
    _allow_any_uid(ns)
    spawner = _spawner()

    ns["wlb_pre_spawn_hook"](spawner)

    assert "TMPDIR" not in spawner.environment


def test_denylista_obejmuje_workspace_i_podsciezki(tmp_path, monkeypatch):
    """#318: deny-lista jest absolutna — /workspace i wszystko pod nim."""
    ns, _ = load_hooks(tmp_path / "state", monkeypatch, now=0)
    assert ns["_wlb_denied"]("/workspace") is True
    assert ns["_wlb_denied"]("/workspace/.wlb-export-queue/x") is True
    assert ns["_wlb_denied"]("/workspace2/x") is False


def test_reap_display_usuwa_tylko_artefakty_wlasciciela(tmp_path, monkeypatch):
    """#318: gniazda/locki X i pliki .vnc tylko właściciela; obce pliki i katalogi nietknięte."""
    tmp_root = tmp_path / "tmp"
    (tmp_root / ".X11-unix").mkdir(parents=True)
    (tmp_root / ".X11-unix" / "X77").write_text("", encoding="utf-8")
    (tmp_root / ".X77-lock").write_text("", encoding="utf-8")
    (tmp_root / "random-file").write_text("", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".vnc").mkdir(parents=True)
    (home / ".vnc" / "a.pid").write_text("", encoding="utf-8")
    (home / ".vnc" / "a.log").write_text("", encoding="utf-8")
    (home / ".vnc" / "other.txt").write_text("", encoding="utf-8")
    xauth = tmp_path / "Xauthority"
    xauth.write_text("", encoding="utf-8")
    monkeypatch.setenv("WLB_TMP_ROOT", str(tmp_root))
    monkeypatch.setenv("WLB_XAUTHORITY", str(xauth))
    ns, calls = load_hooks(tmp_path / "state", monkeypatch, now=4)
    ns["pwd"] = _fake_pwd(str(home))
    _allow_any_uid(ns)

    ns["_wlb_reap_display"](_spawner(), "tester1", str(os.getuid()))

    assert not (tmp_root / ".X11-unix" / "X77").exists()
    assert not (tmp_root / ".X77-lock").exists()
    assert (tmp_root / "random-file").exists()
    assert not (home / ".vnc" / "a.pid").exists()
    assert not (home / ".vnc" / "a.log").exists()
    assert (home / ".vnc" / "other.txt").exists()
    assert xauth.exists(), ".Xauthority (trwały) nie może zniknąć"
    assert ["xauth", "-f", str(xauth), "remove", ":77"] in calls


def test_fail_secure_sprzatanie_nie_wywraca_stopu(tmp_path, monkeypatch):
    """#318: awaria sprzątania = warning, NIGDY wyjątek blokujący stop."""
    scratch_root = tmp_path / "scratch"
    monkeypatch.setenv("WLB_SCRATCH_ROOT", str(scratch_root))
    ns, _ = load_hooks(tmp_path / "state", monkeypatch, now=5)
    ns["pwd"] = _fake_pwd(str(tmp_path / "home"))
    _allow_any_uid(ns)
    (scratch_root / "jupyter-tester1.service").mkdir(parents=True)
    warnings = []
    spawner = _spawner()
    spawner.log = types.SimpleNamespace(warning=lambda *a, **k: warnings.append(a))

    def boom(_path):
        raise OSError("symulowana awaria")

    ns["shutil"] = types.SimpleNamespace(rmtree=boom)
    ns["wlb_post_stop_hook"](spawner)  # nie może rzucić

    assert warnings, "awaria sprzątania musi zostawić warning w logu"


def test_sprzatanie_pomijane_dla_uid_spoza_zakresu(tmp_path, monkeypatch):
    """#318: przed usunięciem walidujemy uid badacza 10000-59999."""
    scratch_root = tmp_path / "scratch"
    monkeypatch.setenv("WLB_SCRATCH_ROOT", str(scratch_root))
    ns, _ = load_hooks(tmp_path / "state", monkeypatch, now=6)
    ns["pwd"] = _fake_pwd(str(tmp_path / "home"), uid=1234)  # poza zakresem badaczy
    scratch = scratch_root / "jupyter-tester1.service"
    scratch.mkdir(parents=True)

    ns["wlb_post_stop_hook"](_spawner())

    assert scratch.exists(), "uid spoza zakresu 10000-59999 nie może nic usuwać"
