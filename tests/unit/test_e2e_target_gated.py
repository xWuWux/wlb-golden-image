"""Bramka bezpieczeństwa: fixture E2E pulpitu nie może trafić do obrazu produkcyjnego (#277).

Artefakty targetu in-session są legalne tylko w buildach testowych. Ten test jest statyczny:
czyta rolę desktop i packer, nie uruchamia Ansible. W produkcji `wlb_enable_e2e_target=false`
musi wyłączyć wszystkie zadania copy/file/template dotykające ścieżek E2E.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_TASKS = REPO_ROOT / "ansible/roles/desktop/tasks/main.yml"
PACKER_VARIABLES = REPO_ROOT / "packer/variables.pkr.hcl"

# Cztery artefakty, które w obrazie produkcyjnym nie mogą powstać. Dodatkowo łapiemy
# katalog skryptów, katalog markerów runtime i nazwy plików zawierające `wlb-e2e`.
CONTRACT_PATHS = (
    "/opt/wlb/e2e",
    "/etc/xdg/autostart/wlb-e2e-target.desktop",
    "/usr/share/applications/wlb-e2e-mouse.desktop",
    "/etc/tmpfiles.d/wlb-e2e.conf",
)
E2E_MARKERS = (*CONTRACT_PATHS, "/run/wlb/e2e", "wlb-e2e")
PATH_MODULES = {"copy", "file", "template"}
PATH_KEYS = ("dest", "src", "path")
GATE = "wlb_enable_e2e_target"

VARIABLE_RE = re.compile(r'variable\s+"wlb_enable_e2e_target"\s*\{(?P<body>.*?)\n\}', re.S)
DEFAULT_FALSE_RE = re.compile(r"^\s*default\s*=\s*false\s*$", re.M)


def load_tasks() -> list[dict]:
    tasks = yaml.safe_load(DESKTOP_TASKS.read_text(encoding="utf-8"))
    assert isinstance(tasks, list) and tasks, f"{DESKTOP_TASKS}: oczekiwano niepustej listy zadań"
    return tasks


def iter_tasks(tasks: list[dict]):
    """Zadania w blokach `block`/`rescue`/`always` też muszą być sprawdzone."""
    for task in tasks:
        assert isinstance(task, dict), f"niepoprawne zadanie: {task!r}"
        yield task
        for section in ("block", "rescue", "always"):
            nested = task.get(section)
            if isinstance(nested, list):
                yield from iter_tasks(nested)


def string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from string_values(item)


def task_paths(task: dict) -> list[str]:
    for key, value in task.items():
        module = key.rsplit(".", 1)[-1]
        if module not in PATH_MODULES:
            continue
        if isinstance(value, dict):
            for path_key in PATH_KEYS:
                yield from string_values(value.get(path_key))
        else:
            # Rzadki zapis modułu jako string, np. `copy: src=... dest=...`.
            yield from string_values(value)


def when_text(task: dict) -> str:
    value = task.get("when")
    return " ".join(string_values(value)) if value is not None else ""


def e2e_tasks(tasks: list[dict]) -> list[dict]:
    found = []
    for task in iter_tasks(tasks):
        paths = list(task_paths(task))
        if any(marker in path for path in paths for marker in E2E_MARKERS):
            found.append(
                {
                    "name": str(task.get("name", "<bez nazwy>")),
                    "paths": paths,
                    "when": when_text(task),
                }
            )
    return found


def test_every_e2e_path_task_is_gated():
    selected = e2e_tasks(load_tasks())
    missing = [f"{task['name']} ({', '.join(task['paths'])})" for task in selected if GATE not in task["when"]]
    assert not missing, "Zadania E2E bez bramki `when: wlb_enable_e2e_target`: " + "; ".join(missing)


def test_positive_control_and_contract_path_coverage():
    selected = e2e_tasks(load_tasks())
    assert selected, (
        "Kontrola pozytywna nie znalazła żadnego zadania copy/file/template dla ścieżek E2E — "
        "test byłby pusto-zielony; sprawdź ścieżki w ansible/roles/desktop/tasks/main.yml."
    )
    missing = [
        path
        for path in CONTRACT_PATHS
        if not any(path in candidate for task in selected for candidate in task["paths"])
    ]
    assert not missing, "Brak zadania dla ścieżek kontraktu E2E: " + ", ".join(missing)


def test_packer_default_disables_e2e_target():
    text = PACKER_VARIABLES.read_text(encoding="utf-8")
    variables = list(VARIABLE_RE.finditer(text))
    assert len(variables) == 1, (
        f"{PACKER_VARIABLES}: oczekiwano dokładnie jednej zmiennej wlb_enable_e2e_target, znaleziono {len(variables)}"
    )
    body = variables[0].group("body")
    assert DEFAULT_FALSE_RE.search(body), (
        f"Zmienna packer `wlb_enable_e2e_target` musi mieć `default = false`; aktualne ciało: {body!r}"
    )
