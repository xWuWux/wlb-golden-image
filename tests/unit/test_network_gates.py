"""Regresje bramek sieci/utwardzenia (#63, #16), bez KVM i zmian sysctl hosta."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def run_bash(script, cwd, env=None):
    return subprocess.run(  # noqa: S603
        ["bash", "-c", script],  # noqa: S607
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        timeout=15,
    )


def sysctl_policy():
    tasks = yaml.safe_load((ROOT / "ansible/roles/base/tasks/main.yml").read_text())
    content = next(
        t["ansible.builtin.copy"]["content"]
        for t in tasks
        if t.get("ansible.builtin.copy", {}).get("dest") == "/etc/sysctl.d/99-wlb.conf"
    )
    return dict(line.split(" = ") for line in content.splitlines() if line and not line.startswith("#"))


def run_sysctl_contract(tmp_path, broken="", error=False):
    policy = sysctl_policy()
    cases = "\n".join(f"{key}) echo {value} ;;" for key, value in policy.items())
    script = f"""
source '{ROOT}/tests/lib/remote-common.sh'
sysctl() {{
  if [[ $2 == "$BROKEN" ]]; then
    if [[ $READ_ERROR == 1 ]]; then echo '{policy.get(broken, "")}'; return 1; fi
    echo 999; return
  fi
  case $2 in
{cases}
  *) return 1 ;;
  esac
}}
# Pliki coredump nie są przedmiotem tej regresji; nie czytaj konfiguracji hosta.
grep() {{ return 0; }}
source '{ROOT}/tests/acceptance.d/30-sysctl-coredump.sh'
summary
"""
    return run_bash(script, tmp_path, {"BROKEN": broken, "READ_ERROR": str(int(error))})


def test_sysctl_contract_accepts_current_policy(tmp_path):
    assert run_sysctl_contract(tmp_path).returncode == 0


@pytest.mark.parametrize("key", sorted(sysctl_policy()))
def test_every_configured_sysctl_drift_is_detected(tmp_path, key):
    result = run_sysctl_contract(tmp_path, key)
    assert result.returncode != 0, f"Niewykryty dryf {key}: {result.stdout}"


def test_sysctl_read_error_cannot_pass_with_correct_stdout(tmp_path):
    assert run_sysctl_contract(tmp_path, "net.ipv4.conf.all.rp_filter", error=True).returncode != 0


def test_proxy_start_failure_fails_integration_before_vm(tmp_path):
    # Uruchom rzeczywistą funkcję acceptance, izolując kosztowny build i hostowe zależności.
    integration = (ROOT / "ci/integration.sh").read_text()
    acceptance = integration.split("acceptance() {", 1)[1].split("\nsiem_delivery()", 1)[0]
    tests = tmp_path / "tests"
    (tests / "lib").mkdir(parents=True)
    for name, body in {
        "lib/test-pki.sh": "exit 0",
        "run-local.sh": "touch vm-started",
        "acceptance.sh": "echo 'Wynik: 1 PASS, 0 FAIL, 0 SKIP'",
        "stop-local.sh": "exit 0",
    }.items():
        path = tests / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
    script = (
        """
LOGS=. ARTIFACTS=. IMAGE=unused SSH=(true)
sudo() { return 1; }
python3() {
  case $1 in
    tests/syslog_sink.py) exec /bin/sleep 30 ;;
    tests/proxy_sink.py) return 1 ;;
  esac
}
sleep() { /bin/sleep 0.1; }
collect_vm_logs() { :; }
summary() { cat; }
"""
        + "acceptance() {"
        + acceptance
        + "\nacceptance\n"
    )
    result = run_bash(script, tmp_path)
    assert result.returncode != 0, result.stdout
    assert not (tmp_path / "vm-started").exists(), result.stdout


@pytest.mark.parametrize(
    "status,code,expected",
    [(56, "403", 0), (0, "200", 1), (7, "000", 1), (28, "000", 1), (60, "000", 1), (56, "502", 1)],
)
def test_connect_requires_explicit_proxy_denial(tmp_path, status, code, expected):
    """Odmowa proxy ≠ awaria transportu/DNS/certyfikatu (#16, #63)."""
    source = (ROOT / "tests/acceptance-remote.sh").read_text()
    function = source.split("  proxy_denies_connect() {", 1)[1].split("\n  }", 1)[0]
    script = f"""
R1=tester P=http://127.0.0.1:3128
as() {{ echo {code}; return {status}; }}
proxy_denies_connect() {{{function}
}}
proxy_denies_connect https://outside.invalid/
"""
    assert run_bash(script, tmp_path).returncode == expected


def test_connect_denial_over_real_socket(tmp_path):
    """curl faktycznie wysyła CONNECT do lokalnej atrapy, bez dostępu do internetu (#16)."""
    from http.server import ThreadingHTTPServer
    from threading import Thread

    from conftest import load_script

    proxy = load_script("network_proxy_fixture", ROOT / "tests/proxy_sink.py")
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Proxy)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = (ROOT / "tests/acceptance-remote.sh").read_text()
        function = source.split("  proxy_denies_connect() {", 1)[1].split("\n  }", 1)[0]
        script = f"""
R1=tester P=http://127.0.0.1:{server.server_port}
as() {{ shift; "$@"; }}
proxy_denies_connect() {{{function}
}}
proxy_denies_connect https://outside.invalid/
"""
        result = run_bash(script, tmp_path, {"NO_PROXY": "*", "no_proxy": "*"})
        assert result.returncode == 0, result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
