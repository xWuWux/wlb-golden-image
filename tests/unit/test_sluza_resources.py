"""Kontrakt konfiguracji i bezpieczeństwa testów śluzy (#149)."""

from pathlib import Path

import pytest
import yaml
from conftest import load_script
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[2]
ENV = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - systemd config, not HTML
DEFAULTS = yaml.safe_load((ROOT / "ansible/group_vars/all.yml").read_text())
TASKS = yaml.safe_load((ROOT / "ansible/roles/storage/tasks/main.yml").read_text())


def test_role_installs_resource_dropin():
    assert any(
        t.get("ansible.builtin.template", {}).get("dest")
        == "/etc/systemd/system/wlb-sluza-out.service.d/60-resources.conf"
        for t in TASKS
    )


def test_default_render():
    text = (ROOT / "ansible/roles/storage/templates/60-resources.conf.j2").read_text()
    rendered = ENV.from_string(text).render(DEFAULTS)
    for line in [
        "MemoryMax=256M",
        "MemoryHigh=192M",
        "MemorySwapMax=0",
        "TasksMax=32",
        "IOWeight=50",
        "Delegate=no",
        "ProtectControlGroups=yes",
        "OOMPolicy=stop",
        "KillMode=control-group",
    ]:
        assert line in rendered.splitlines()


def validation(values):
    expressions = next(t["ansible.builtin.assert"]["that"] for t in TASKS if "ansible.builtin.assert" in t)
    return all(ENV.compile_expression(expr)(values) for expr in expressions)


def test_default_budget_valid():
    assert validation(DEFAULTS)


@pytest.mark.parametrize(
    "key,value",
    [
        ("wlb_sluza_memory_max_mb", "infinity"),
        ("wlb_sluza_memory_high_mb", 256),
        ("wlb_sluza_memory_high_mb", 0),
        ("wlb_sluza_tasks_max", 10),
        ("wlb_sluza_tasks_max", "32"),
        ("wlb_sluza_tasks_max", True),
        ("wlb_sluza_io_weight", 0),
        ("wlb_sluza_io_weight", 10001),
    ],
)
def test_invalid_budget_rejected(key, value):
    assert not validation({**DEFAULTS, key: value})


@pytest.mark.parametrize("memory,tasks", [(0, 32), (512 * 1024**2, 32), (256 * 1024**2, 512)])
def test_probe_refuses_unsafe_workload(memory, tasks):
    module = load_script("sluza_resources", ROOT / "tests/sluza_resources.py")
    with pytest.raises(ValueError):
        module.budget(memory, tasks)


def test_probe_control_is_bounded():
    module = load_script("sluza_resources", ROOT / "tests/sluza_resources.py")
    assert module.budget(256 * 1024**2, 32) == (320 * 1024**2, 40)
    for payload in [module.MEMORY, module.FORK, module.DENIED]:
        compile(payload, "probe", "exec")
