"""Testy wyniku E2E pulpitu (#277-B) — bez przeglądarki i bez VM.

Sprawdzają to, co da się rozstrzygnąć offline: kontrakt `mouse.txt`, walidację
`target.json` (#277-A), macierz bramkowania scenariuszy oraz mapowanie wyniku na
kod wyjścia. Kluczowa własność: mysz OK nie może zaliczyć klawiatury.
"""

import json

import pytest
from conftest import REPO_ROOT, load_script

e2e = load_script("desktop_e2e_novnc", REPO_ROOT / "tests" / "desktop-e2e-novnc.py")


def make_e2e(tmp_path, desktop="required", interaction="required"):
    cfg = {
        "hub": "https://localhost",
        "user": "u01",
        "pass": "secret",
        "desktop": desktop,
        "interaction": interaction,
        "timeout": 60,
        "ssh": "",
        "ca": "",
        "artifacts": tmp_path,
    }
    return e2e.E2E(cfg, tmp_path)


def target(**overrides):
    data = {
        "schema": "wlb.e2e-target/v1",
        "session_id": "6f1c2f34-0000-4000-8000-000000000000",
        "screen": {"w": 1280, "h": 800},
        "keyboard": {"title": "E2E"},
        "button": {"x": 100, "y": 200, "w": 120, "h": 40},
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("rc=0\n", 0),
        ("rc=1", 1),
        ("rc = 0", 0),
        ('{"rc": 0, "x": 10, "y": 20}', 0),
        ('{"rc": "3"}', 3),
        ("", None),
        ("ok", None),
        ("rc=abc", None),
        ('{"x": 1}', None),
    ],
)
def test_parse_mouse_rc(text, expected):
    assert e2e._parse_mouse_rc(text) == expected


def test_validate_target_accepts_contract():
    parsed = e2e._validate_target(target())
    assert parsed["session_id"].startswith("6f1c2f34")
    assert parsed["screen"] == {"w": 1280, "h": 800}
    assert parsed["button"] == {"x": 100, "y": 200, "w": 120, "h": 40}
    assert parsed["keyboard"] == {"title": "E2E"}


@pytest.mark.parametrize(
    "broken",
    [
        [],
        {"schema": "wlb.e2e-target/v0"},
        target(session_id=""),
        target(screen={"w": 0, "h": 800}),
        target(screen={"w": "1280"}),
        target(button={"x": 1, "y": 2, "w": 0, "h": 4}),
        {"schema": "wlb.e2e-target/v1", "session_id": "x", "screen": {"w": 1, "h": 1}},
    ],
)
def test_validate_target_rejects(broken):
    with pytest.raises(e2e.ConfigError):
        e2e._validate_target(broken)


def test_gating_matrix(tmp_path):
    absent = make_e2e(tmp_path, desktop="absent").result["scenarios"]
    # baza bez pulpitu: launcher bramkuje (kafelek Desktop = regresja lekkości), reszta pominięta
    assert [name for name in e2e.SCENARIO_ORDER if absent[name]["gating"]] == ["launcher"]

    required = make_e2e(tmp_path).result["scenarios"]
    assert all(required[name]["gating"] for name in e2e.SCENARIO_ORDER)

    optional = make_e2e(tmp_path, interaction="optional").result["scenarios"]
    assert not optional["pointer"]["gating"]
    assert not optional["keyboard"]["gating"]
    # render/resize/reconnect nadal bramkują: flavor ma pulpit i musi go pokazać
    assert optional["render"]["gating"] and optional["resize"]["gating"] and optional["reconnect"]["gating"]


def test_finalize_pass_for_headless_base(tmp_path):
    run = make_e2e(tmp_path, desktop="absent")
    run.scenario("launcher", "pass", "brak kafelka Desktop")
    run.skip_downstream("flavor bez pulpitu")
    assert run.finalize() == 0
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["schema"] == e2e.SCHEMA
    assert result["status"] == "pass"
    assert result["scenarios"]["render"]["status"] == "not_run"


def test_finalize_fails_when_base_exposes_desktop_tile(tmp_path):
    run = make_e2e(tmp_path, desktop="absent")
    run.scenario("launcher", "fail", "WLB_E2E_DESKTOP=absent, a Launcher wystawia kafelek Desktop")
    assert run.finalize() == 2
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "fail"
    assert "launcher" in result["reason"]


def test_mouse_pass_does_not_pass_keyboard(tmp_path):
    run = make_e2e(tmp_path)
    run.scenario("launcher", "pass", "kafelek Desktop")
    run.scenario("render", "pass", "canvas 1280×800")
    run.scenario("pointer", "pass", "mouse.txt rc=0")
    run.scenario("keyboard", "fail", "keyboard.txt != nonce")
    run.scenario("resize", "not_run", "brak")
    run.scenario("reconnect", "not_run", "brak")
    assert run.finalize() == 2
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "fail"
    assert result["scenarios"]["pointer"]["status"] == "pass"
    assert "keyboard" in result["reason"]


def test_finalize_reports_error_for_gating_config_problem(tmp_path):
    run = make_e2e(tmp_path)
    run.top_error = "brak roota na VM (WLB_E2E_SSH)"
    assert run.finalize() == 1
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "error"


def test_optional_interaction_is_advisory(tmp_path):
    run = make_e2e(tmp_path, interaction="optional")
    run.scenario("launcher", "pass", "kafelek Desktop")
    run.scenario("render", "pass", "canvas")
    run.scenario("pointer", "fail", "mouse.txt rc=1")
    run.scenario("keyboard", "fail", "keyboard.txt != nonce")
    run.scenario("resize", "pass", "canvas żyje")
    run.scenario("reconnect", "pass", "ta sama sesja")
    assert run.finalize() == 0
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "pass"
    assert "tryb raportowy" in result["reason"]


class FakePage:
    """Minimalna strona: canvas = viewport minus pasek noVNC o zadanej wysokości."""

    def __init__(self, chrome_h=60, chrome_w=0, stuck=False):
        self.chrome_h = chrome_h
        self.chrome_w = chrome_w
        self.stuck = stuck
        self.viewport_size = {"width": 1280, "height": 800}
        self.sets = 0

    def set_viewport_size(self, size):
        self.viewport_size = dict(size)
        self.sets += 1

    def evaluate(self, _script):
        if self.stuck:
            return {"found": True, "count": 1, "colors": 42, "w": 1680, "h": 1050, "cssW": 1680, "cssH": 1050}
        return {
            "found": True,
            "count": 1,
            "readable": True,
            "colors": 42,
            "w": self.viewport_size["width"] - self.chrome_w,
            "h": self.viewport_size["height"] - self.chrome_h,
            "cssW": self.viewport_size["width"] - self.chrome_w,
            "cssH": self.viewport_size["height"] - self.chrome_h,
        }


def test_fit_viewport_calibrates_novnc_chrome(tmp_path):
    run = make_e2e(tmp_path)
    run.clock.sleep = lambda _seconds: None
    page = FakePage(chrome_h=44)
    fit = run._fit_viewport(page, target(screen={"w": 1680, "h": 1050}))
    assert fit["ok"] is True
    # pasek 44 px nie jest zgadywany stałą: viewport = 1050 + 44, canvas = 1680x1050
    assert page.viewport_size == {"width": 1680, "height": 1094}


def test_fit_viewport_reports_failure_without_matching_screen(tmp_path):
    run = make_e2e(tmp_path)
    run.clock.sleep = lambda _seconds: None
    fit = run._fit_viewport(FakePage(stuck=True), target())
    assert fit["ok"] is False
    assert fit["sample"]["w"] == 1680
