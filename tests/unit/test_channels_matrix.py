"""Walidacja matrycy kanałów eksportu/importu (#292, inkrement 1).

Matryca `tests/channels.yaml` jest jednym źródłem prawdy dla testów akceptacyjnych,
raportu CI i dokumentacji. Ten test pilnuje schematu oraz — co ważniejsze — tego,
że harness `tests/acceptance.d/46-kanaly-eksportu.sh` realizuje DOKŁADNIE te wpisy
(bez dryfu metadata: id, surface, direction, expected, control).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "tests" / "channels.yaml"
FRAGMENT = ROOT / "tests" / "acceptance.d" / "46-kanaly-eksportu.sh"

REQUIRED_FIELDS = ("id", "direction", "surface", "expected", "probe", "evidence", "owner", "test", "required")
DIRECTIONS = {"export", "import", "internal"}
SURFACES = {"jupyter", "rstudio", "jamovi", "desktop", "network", "client"}
EXPECTATIONS = {"denied", "allowed", "known_open"}
PROBE_TYPES = {"http", "fs", "network", "version", "capture"}
PREFIX_SURFACE = {
    "JL-": "jupyter",
    "JM-": "jamovi",
    "DT-": "desktop",
    "NET-": "network",
    "RS-": "rstudio",
    "CL-": "client",
}
OWNER_BY_SURFACE = {
    "jupyter": "platform",
    "jamovi": "histologia",
    "desktop": "platform",
    "network": "platform",
    "rstudio": "rstudio",
    "client": "platform",
}

# Wywołania harnessu: ID KIERUNEK OCZEKIWANIE "OPIS" -- SONDY...
CALL_RE = re.compile(r'^\s*(wlb_probe|wlb_control)\s+(\S+)\s+(\S+)\s+(\S+)\s+"', re.MULTILINE)
KNOWN_OPEN_RE = re.compile(r'^\s*wlb_known_open\s+(\S+)\s+(\S+)\s+"', re.MULTILINE)


@pytest.fixture(scope="module")
def matrix() -> dict:
    return yaml.safe_load(MATRIX.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def channels(matrix: dict) -> list[dict]:
    return matrix["channels"]


@pytest.fixture(scope="module")
def entries(channels: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in channels}


@pytest.fixture(scope="module")
def fragment_text() -> str:
    return FRAGMENT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calls(fragment_text: str) -> dict[str, dict]:
    parsed: dict[str, dict] = {}
    for kind, channel_id, direction, expected in CALL_RE.findall(fragment_text):
        parsed[channel_id] = {
            "kind": kind,
            "direction": direction,
            "expected": expected,
            "control": kind == "wlb_control",
        }
    return parsed


def test_top_level_schema(matrix: dict) -> None:
    assert matrix["schema"] == "wlb.channels/v1"
    assert isinstance(matrix["channels"], list)
    assert matrix["channels"], "matryca nie może być pusta"


def test_required_fields(channels: list[dict]) -> None:
    for entry in channels:
        missing = [
            name
            for name in REQUIRED_FIELDS
            if entry.get(name) is None or (isinstance(entry[name], str) and not entry[name])
        ]
        assert not missing, f"{entry.get('id', '?')}: brak pól {missing}"


def test_required_is_bool(channels: list[dict]) -> None:
    for entry in channels:
        assert isinstance(entry.get("required"), bool), (
            f"{entry['id']}: pole 'required' musi być wartością logiczną (true/false)"
        )


def test_unique_ids(channels: list[dict]) -> None:
    ids = [entry["id"] for entry in channels]
    duplicates = sorted({channel_id for channel_id in ids if ids.count(channel_id) > 1})
    assert not duplicates, f"duplikaty id: {duplicates}"


def test_enum_values(channels: list[dict]) -> None:
    for entry in channels:
        assert entry["direction"] in DIRECTIONS, entry["id"]
        assert entry["surface"] in SURFACES, entry["id"]
        assert entry["expected"] in EXPECTATIONS, entry["id"]
        assert entry["probe"]["type"] in PROBE_TYPES, entry["id"]


def test_denied_has_expectation(channels: list[dict]) -> None:
    for entry in channels:
        if entry["expected"] != "denied":
            continue
        probe = entry["probe"]
        assert "expect_status" in probe or "expect_exit" in probe, (
            f"{entry['id']}: denied musi mieć expect_status albo expect_exit"
        )


def test_known_open_has_why(channels: list[dict]) -> None:
    for entry in channels:
        if entry["expected"] == "known_open":
            assert entry.get("why"), f"{entry['id']}: known_open wymaga uzasadnienia (why)"
            assert entry.get("owner"), f"{entry['id']}: known_open wymaga jawnego właściciela (owner)"


def test_every_denied_group_has_positive_control(channels: list[dict]) -> None:
    for surface in SURFACES:
        group = [entry for entry in channels if entry["surface"] == surface]
        denied = [entry for entry in group if entry["expected"] == "denied"]
        if not denied:
            continue
        controls = [entry for entry in group if entry.get("control") and entry["expected"] == "allowed"]
        assert controls, f"surface {surface}: denied bez kontroli pozytywnej w tej samej grupie"


def test_id_prefix_matches_surface_and_owner(entries: dict[str, dict]) -> None:
    for channel_id, entry in entries.items():
        prefix = next((pref for pref in PREFIX_SURFACE if channel_id.startswith(pref)), None)
        assert prefix, f"{channel_id}: nieznany prefiks id"
        assert PREFIX_SURFACE[prefix] == entry["surface"], f"{channel_id}: prefiks != surface"
        assert OWNER_BY_SURFACE[entry["surface"]] == entry["owner"], f"{channel_id}: owner != surface"


def test_evidence_letters(entries: dict[str, dict]) -> None:
    for channel_id, entry in entries.items():
        assert set(entry["evidence"]) <= {"R", "U", "V"}, f"{channel_id}: evidence={entry['evidence']}"
        assert entry["evidence"], channel_id


def test_probe_type_fields(entries: dict[str, dict]) -> None:
    for channel_id, entry in entries.items():
        probe = entry["probe"]
        kind = probe["type"]
        if kind == "http":
            assert probe.get("method") in {"GET", "PUT", "POST", "DELETE"}, channel_id
            assert str(probe.get("path", "")).startswith("/"), channel_id
            status = probe.get("expect_status")
            if status is not None:
                allowed = status if isinstance(status, list) else [status]
                assert all(isinstance(code, int) for code in allowed), channel_id
        elif kind == "fs":
            assert probe.get("path"), channel_id
            assert probe.get("operation") in {"read", "write"}, channel_id
            assert "expect_exit" in probe, channel_id
        elif kind == "network":
            assert probe.get("via") in {"proxy", "direct"}, channel_id
            assert probe.get("target"), channel_id
        elif kind == "version":
            assert probe.get("package"), channel_id
            assert re.fullmatch(r"\d+\.\d+\.\d+", str(probe.get("expect_version"))), channel_id
        elif kind == "capture":
            assert probe.get("tool"), channel_id
            assert probe.get("fixture"), channel_id


def test_scope_minimum(entries: dict[str, dict]) -> None:
    """Inkrement 1 musi pokrywać cztery obszary i wszystkie warianty ścieżek."""
    ids = set(entries)
    for required in (
        "JL-SAVE",
        "JL-FILES-DL",
        "JL-NBCONVERT",
        "JL-CONTENTS-BASE64",
        "JM-SANDBOX-HOME-READ",
        "JM-ETC-SHADOW-READ",
        "DT-SLUIZA-OUT-WRITE",
        "DT-SLUIZA-IN-WRITE",
        "DT-JRDP-VERSION",
        "NET-PROXY-MIRROR",
        "NET-DIRECT-IP",
        "RS-TRANSFER-PATHS",
        "CL-PRINT",
        "CL-SAVE-PAGE",
        "CL-CLIPBOARD",
        "CL-SCREENSHOT",
    ):
        assert required in ids, f"brak kanału {required}"
    variants = {"DOTDOT", "ENCODED", "SLASH", "DOT", "ABS", "SYMLINK"}
    present = {channel_id.rsplit("-", 1)[-1] for channel_id in ids if channel_id.startswith("JL-TRAVERSAL-")}
    assert variants <= present, f"brak wariantów traversal: {sorted(variants - present)}"


def test_test_field_points_to_existing_fragment(entries: dict[str, dict]) -> None:
    for channel_id, entry in entries.items():
        name = entry["test"].split("/")[-1]
        assert (ROOT / "tests" / "acceptance.d" / f"{name}.sh").is_file(), f"{channel_id}: {entry['test']}"


def test_fragment_covers_matrix_exactly(entries: dict[str, dict], calls: dict[str, dict], fragment_text: str) -> None:
    known_open = {channel_id for channel_id, _ in KNOWN_OPEN_RE.findall(fragment_text)}
    covered = set(calls) | known_open
    assert covered == set(entries), (
        f"dryf harnessu: brak w harnessie {sorted(set(entries) - covered)}; nadmiarowe {sorted(covered - set(entries))}"
    )


def test_fragment_metadata_matches_matrix(entries: dict[str, dict], calls: dict[str, dict]) -> None:
    for channel_id, call in calls.items():
        entry = entries[channel_id]
        assert call["direction"] == entry["direction"], f"{channel_id}: direction"
        assert call["expected"] == entry["expected"], f"{channel_id}: expected"
        assert call["control"] == bool(entry.get("control")), f"{channel_id}: control"


def test_known_open_not_asserted(entries: dict[str, dict], calls: dict[str, dict], fragment_text: str) -> None:
    known_open = {channel_id for channel_id, _ in KNOWN_OPEN_RE.findall(fragment_text)}
    for channel_id, entry in entries.items():
        if entry["expected"] == "known_open":
            assert channel_id in known_open, f"{channel_id}: known_open musi iść przez wlb_known_open"
            assert channel_id not in calls, f"{channel_id}: known_open nie może być asercją"


def test_jrdp_pin_is_audited_version(entries: dict[str, dict]) -> None:
    # Pin 3.0.1 = wersja audytowana w #140/#277 (noVNC bez UI transferu plików).
    assert entries["DT-JRDP-VERSION"]["probe"]["expect_version"] == "3.0.1"


def test_harness_self_test() -> None:
    """Harness musi pomyślnie przejść smoke test klasyfikacji kodów (124/127 -> rc=2 error)."""
    proc = subprocess.run(  # noqa: S603
        ["/bin/bash", str(FRAGMENT), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"self-test failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "Self-test passed!" in proc.stdout


# --- Spójność required: YAML (źródło prawdy) vs harness (wlb_ch_required) -----------------
# Harness nie czyta YAML — liczy required z prefiksu ID. Ten test wyciąga SAMĄ FUNKCJĘ
# wlb_ch_required() i wykonuje ją w bashu, więc porównuje faktyczną semantykę `case` (alternatywy,
# kolejność, globbing), a nie jej ręcznie przepisany regex. Rozjazd failuje w CI, zamiast po cichu
# zmieniać bramkowanie. Ograniczenie: to nadal DWA źródła (YAML + prefiksy w harnessie); test je
# wiąże, ale nie sprawia, że YAML jest czytany w runtime — patrz komentarz przy teście.

REQUIRED_FN = re.compile(r"^wlb_ch_required\(\)\s*\{.*?^\}", re.S | re.M)
REQUIRED_TIMEOUT_S = 10


def _harness_required_map(fragment: Path, ids: list[str]) -> dict[str, int]:
    """Uruchamia wlb_ch_required() z fragmentu dla podanych ID; zwraca {id: 0|1}.

    Wyciągamy tylko definicję funkcji (bez reszty harnessu, żeby nie odpalać sond), walidujemy
    składnię bash -n i wykonujemy w jednym procesie. To dokładna semantyka `case`, nie regex.
    """
    text = fragment.read_text(encoding="utf-8")
    match = REQUIRED_FN.search(text)
    assert match, "harness nie zawiera funkcji wlb_ch_required()"
    func = match.group(0)
    script = func + '\nfor id in "$@"; do printf "%s\\t%s\\n" "$id" "$(wlb_ch_required "$id")"; done\n'
    proc = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", script, "wlb-ch-required", *ids],
        capture_output=True,
        text=True,
        timeout=REQUIRED_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"wlb_ch_required() nie wykonał się: rc={proc.returncode}\n{proc.stderr}"
    mapping: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        channel_id, _, raw = line.partition("\t")
        assert raw in {"0", "1"}, f"{channel_id}: wlb_ch_required zwróciło {raw!r} (oczekiwano 0/1)"
        mapping[channel_id] = int(raw)
    assert set(mapping) == set(ids), f"brak wyników dla ID: {sorted(set(ids) - set(mapping))}"
    return mapping


def _required_mismatches(channels: list[dict], mapping: dict[str, int]) -> list[str]:
    return [
        f"{entry['id']}: YAML required={entry['required']}, harness wlb_ch_required={bool(mapping[entry['id']])}"
        for entry in channels
        if bool(mapping[entry["id"]]) != entry["required"]
    ]


def test_harness_required_matches_matrix(channels: list[dict]) -> None:
    """required w YAML musi zgadzać się z wlb_ch_required() w harnessie — inaczej gating
    (required+error -> blokada) zależy od prefiksu ID, a nie od matrycy."""
    mapping = _harness_required_map(FRAGMENT, [entry["id"] for entry in channels])
    mismatches = _required_mismatches(channels, mapping)
    assert not mismatches, "rozjazd required YAML <-> harness:\n" + "\n".join(mismatches)


def test_harness_required_detects_drift(tmp_path: Path, channels: list[dict]) -> None:
    """Test negatywny: spreparowany harness z rozjechaną gałęzią MUSI zostać wykryty.

    Bez tego zielony wynik mógłby być pusty (np. ekstrakcja złapałaby tylko fallback `*`).
    """
    text = FRAGMENT.read_text(encoding="utf-8")
    mutated = text.replace("JM-*) echo 0 ;;", "JM-*) echo 1 ;;", 1)
    assert mutated != text, "fixture: nie znaleziono gałęzi JM-*) do zmutowania"
    bad_fragment = tmp_path / "46-kanaly-eksportu-mutated.sh"
    bad_fragment.write_text(mutated, encoding="utf-8")
    mapping = _harness_required_map(bad_fragment, [entry["id"] for entry in channels])
    mismatches = _required_mismatches(channels, mapping)
    assert mismatches, "test nie wykrył rozjazdu po mutacji gałęzi JM-*) — bramka jest pusta"
    assert any(item.startswith("JM-SANDBOX-HOME-READ") for item in mismatches)


def test_known_open_is_not_required(channels: list[dict]) -> None:
    """known_open to raport ryzyka, nie bramka — nie może być required=true (gating by je blokował)."""
    bad = [entry["id"] for entry in channels if entry["expected"] == "known_open" and entry["required"]]
    assert not bad, f"known_open oznaczone jako required (zabronione): {bad}"
