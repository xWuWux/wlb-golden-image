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
    # TigerVNC: tylko <host>:<d>.pid/.log skorelowane z DISPLAY są reapowane.
    (home / ".vnc" / "lab-test01:77.pid").write_text("", encoding="utf-8")
    (home / ".vnc" / "lab-test01:77.log").write_text("", encoding="utf-8")
    # Dane badacza: blanket *.pid/*.log NIE może ginąć (deny-lista /workspace).
    (home / ".vnc" / "a.pid").write_text("", encoding="utf-8")
    (home / ".vnc" / "keepme.log").write_text("", encoding="utf-8")
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
    assert not (home / ".vnc" / "lab-test01:77.pid").exists()
    assert not (home / ".vnc" / "lab-test01:77.log").exists()
    assert (home / ".vnc" / "a.pid").exists(), "blanket *.pid nie może być usuwany"
    assert (home / ".vnc" / "keepme.log").exists(), "dane badacza w ~/.vnc muszą przeżyć"
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


def test_pre_spawn_domyka_osierocona_sesje_jako_interrupted(tmp_path, monkeypatch):
    """#97/#98: pre_spawn wykrywa stary plik stanu (np. po awaryjnym restarcie huba),
    domyka poprzednią sesję jako 'interrupted:<source>' przez wlb-usage-record ze starym session_id,
    po czym uruchamia nową sesję ze świeżym session_id i nowym plikiem stanu."""
    state_file = tmp_path / "jupyter-tester1.service.json"
    state_file.write_text(
        json.dumps(
            {
                "session_id": "sess-orphaned-99",
                "start_wall": 1_234_567,
                "lab_source": "spawner_env",
            }
        ),
        encoding="utf-8",
    )
    ns, calls = load_hooks(tmp_path, monkeypatch, now=1_235_000, monotonic=100.0)
    spawner = _spawner()

    ns["wlb_pre_spawn_hook"](spawner)

    # 1. Poprzednia sesja domknięta jako interrupted
    rec = _call(calls, "wlb-usage-record")
    assert rec is not None, "powinien powstać rekord interrupted dla osieroconej sesji"
    # argumenty: [prog, unit, sid, lab, start, stop, duration, status]
    assert rec[1] == "jupyter-tester1.service"
    assert rec[2] == "sess-orphaned-99", "rekord musi dotyczyć starego session_id"
    assert rec[3] == "lab-x"
    assert rec[4] == "1234567"
    assert rec[5] == "", "stop_wall pusty (null w rekordzie, nie epocha 1970)"
    assert rec[6] == "", "duration pusty"
    assert rec[7] == "interrupted:spawner_env"

    # 2. Nowa sesja startuje z unikalnym session_id
    assert spawner._wlb_session != "sess-orphaned-99"
    start_call = _call(calls, "wlb-session-log", "start")
    assert start_call is not None
    assert start_call[4] == spawner._wlb_session

    # 3. Plik stanu na dysku został nadpisany nową sesją
    new_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert new_state["session_id"] == spawner._wlb_session
    assert new_state["start_wall"] == 1_235_000
    assert new_state["lab_source"] == "spawner_env"


def test_pre_spawn_osierocona_sesja_bez_start_wall_przekazuje_pusty_czas(tmp_path, monkeypatch):
    """#97/#98: brak start_wall w osieroconym stanie -> pusty argument w wywołaniu wlb-usage-record,
    nigdy '0' czy 'None' udające czas."""
    state_file = tmp_path / "jupyter-tester1.service.json"
    state_file.write_text(
        json.dumps(
            {
                "session_id": "sess-no-start",
                "lab_source": "spawner_env",
            }
        ),
        encoding="utf-8",
    )
    ns, calls = load_hooks(tmp_path, monkeypatch, now=2_000_000, monotonic=200.0)
    spawner = _spawner()

    ns["wlb_pre_spawn_hook"](spawner)

    rec = _call(calls, "wlb-usage-record")
    assert rec is not None
    assert rec[2] == "sess-no-start"
    assert rec[4] == "", "brak start_wall to pusty string -> null w JSON"
    assert rec[7] == "interrupted:spawner_env"


def test_pre_spawn_czysta_sesja_nie_wywoluje_interrupted(tmp_path, monkeypatch):
    """#97: pierwszy start sesji (brak pliku stanu) nie woła wlb-usage-record interrupted."""
    ns, calls = load_hooks(tmp_path, monkeypatch, now=1_000_000, monotonic=50.0)
    spawner = _spawner()

    ns["wlb_pre_spawn_hook"](spawner)

    assert _call(calls, "wlb-usage-record") is None
    assert _call(calls, "wlb-session-log", "start") is not None


def test_pre_spawn_uszkodzony_plik_stanu_nie_wywraca_spawnu(tmp_path, monkeypatch):
    """#97: uszkodzony/niepełny JSON w stanie sesji jest ignorowany (fail-secure),
    nie blokuje startu nowego serwera."""
    (tmp_path / "jupyter-tester1.service.json").write_text("{ niepoprawny json ...", encoding="utf-8")
    ns, calls = load_hooks(tmp_path, monkeypatch, now=1_000_000, monotonic=50.0)
    spawner = _spawner()

    ns["wlb_pre_spawn_hook"](spawner)  # nie rzuca błędu

    assert _call(calls, "wlb-usage-record") is None
    assert _call(calls, "wlb-session-log", "start") is not None
    assert spawner._wlb_session


def test_wlb_ident_normalizuje_unit_name_bez_sufiksu(tmp_path, monkeypatch):
    """#97/#318: spawner.unit_name w SystemdSpawner/TLJH nie zawiera .service (np. 'jupyter-tester1').
    Hook musi znormalizować go do .service, aby scratch i stan były spójne z samplerem i testami."""
    scratch_root = tmp_path / "scratch"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("WLB_SCRATCH_ROOT", str(scratch_root))
    ns, _ = load_hooks(state_dir, monkeypatch, now=10, monotonic=10.0)
    ns["pwd"] = _fake_pwd(str(tmp_path / "home"), uid=10001)
    _allow_any_uid(ns)
    spawner = _spawner(unit_name="jupyter-tester1")  # bez .service

    ns["wlb_pre_spawn_hook"](spawner)

    expected = str(scratch_root / "jupyter-tester1.service")
    assert spawner.environment["TMPDIR"] == expected
    assert os.path.isdir(expected)
    assert (state_dir / "jupyter-tester1.service.json").is_file()

    ns["wlb_post_stop_hook"](spawner)
    assert not os.path.exists(expected)
    assert not (state_dir / "jupyter-tester1.service.json").exists()


def test_wlb_ident_wola_ensure_user_gdy_konto_jeszcze_nie_istnieje(tmp_path, monkeypatch):
    """#97/#318: przy pierwszym spawnie użytkownika konto w systemie (/etc/passwd) jeszcze nie istnieje
    (TLJH UserCreatingSpawner tworzy je dopiero w start()). Hook musi wywołać ensure_user,
    aby poprawnie uzyskać UID badacza i utworzyć scratch."""
    scratch_root = tmp_path / "scratch"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("WLB_SCRATCH_ROOT", str(scratch_root))
    ns, _ = load_hooks(state_dir, monkeypatch, now=20, monotonic=20.0)
    _allow_any_uid(ns)

    user_db = {}
    called = []

    class FakeTLJHUser:
        @staticmethod
        def ensure_user(name):
            called.append(name)
            user_db[name] = types.SimpleNamespace(pw_uid=10002, pw_gid=10002, pw_dir=str(tmp_path / "home"))

    class FakePwd:
        @staticmethod
        def getpwnam(name):
            if name in user_db:
                return user_db[name]
            raise KeyError(name)

    ns["pwd"] = FakePwd
    monkeypatch.setitem(os.sys.modules, "tljh", types.ModuleType("tljh"))
    tljh_user_mod = types.ModuleType("tljh.user")
    tljh_user_mod.ensure_user = FakeTLJHUser.ensure_user
    monkeypatch.setitem(os.sys.modules, "tljh.user", tljh_user_mod)

    spawner = _spawner(unit_name="jupyter-newuser")
    spawner.user = types.SimpleNamespace(name="newuser")

    ns["wlb_pre_spawn_hook"](spawner)

    assert called == ["jupyter-newuser"]
    expected = str(scratch_root / "jupyter-newuser.service")
    assert spawner.environment["TMPDIR"] == expected
    assert os.path.isdir(expected)
