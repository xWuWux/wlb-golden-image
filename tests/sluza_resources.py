#!/usr/bin/env python3
"""Akceptacja #149: rzeczywista konfiguracja usługi + izolowane, ograniczone próby jądra.

Uruchamiany jako root w testowej VM: python3 tests/sluza_resources.py LOGIN.
Nie obciąża produkcyjnej kolejki i nie wyłącza limitów na VM.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SERVICE = "wlb-sluza-out.service"
DROPIN = Path("/etc/systemd/system/wlb-sluza-out.service.d/60-resources.conf")
MEMORY = "import sys; data = bytearray(int(sys.argv[1])); print(len(data), flush=True)"
FORK = """import errno, os, signal, sys, time
from pathlib import Path
children = []
blocked = False
try:
    for _ in range(int(sys.argv[1])):
        try:
            pid = os.fork()
        except OSError as exc:
            if exc.errno != errno.EAGAIN: raise
            blocked = True
            break
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        children.append(pid)
    cg = Path('/sys/fs/cgroup' + Path('/proc/self/cgroup').read_text().strip().split('::')[1])
    events = dict(line.split() for line in (cg / 'pids.events').read_text().splitlines())
    assert blocked == (sys.argv[2] == 'blocked')
    assert (int(events['max']) > 0) == blocked
finally:
    for pid in children:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
"""
DENIED = """import errno, os, sys
from pathlib import Path
p = Path(sys.argv[1])
assert p.exists(), 'Brak celu nie jest dowodem odmowy'
try:
    if sys.argv[2] == 'chmod': p.chmod(p.stat().st_mode & 0o777)
    else: p.write_text(str(os.getpid()) if sys.argv[2] == 'pid' else sys.argv[2])
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), repr(exc)
else:
    raise AssertionError('Nieuprzywilejowany zapis powiódł się')
"""


def run(*args: str) -> str:
    """Polecenie bez powłoki; stdout, wyjątek przy błędzie lub po 15 s."""
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout.strip()  # noqa: S603


def prop(unit: str, name: str) -> str:
    return run("systemctl", "show", "--value", f"--property={name}", unit)


def budget(memory: int, tasks: int) -> tuple[int, int]:
    """Dobierz bounded workload; większe budżety wymagają kalibracji scenariusza CI."""
    if not 64 * 1024**2 <= memory <= 384 * 1024**2 or not 16 <= tasks <= 64:
        raise ValueError("Budżet poza bezpieczną obwiednią testu: 64–384 MiB, 16–64 tasks")
    return memory + 64 * 1024**2, tasks + 8


def probe(
    root: Path, label: str, code: str, args: list[str], control: bool = False, oom_hard: bool = False
) -> tuple[str, str]:
    """Jednostka testowa z kopią drop-in; kontrola ma nadal 512 MiB/128 tasks i timeout."""
    unit = f"wlb149-{root.name}-{label}.service"
    # Slice pozostaje aktywny po OOM dziecka: zachowuje hierarchiczne liczniki memory.events.
    # oom > 0 odróżnia osiągnięcie limitu cgroup od samego SIGKILL/globalnego OOM.
    slice_name = "wlb149" + root.name.replace("-", "") + label.replace("-", "") + ".slice"
    slice_path = Path("/run/systemd/system") / slice_name
    slice_path.write_text("[Slice]\nMemoryAccounting=yes\nMemoryMax=768M\nMemorySwapMax=0\nTasksMax=192\n")
    unit_path = Path("/run/systemd/system") / unit
    drop = Path(str(unit_path) + ".d")
    script = root / f"{label}.py"
    script.write_text(code)
    drop.mkdir()
    shutil.copyfile(DROPIN, drop / "60-resources.conf")
    if control:
        (drop / "90-control.conf").write_text("[Service]\nMemoryHigh=480M\nMemoryMax=512M\nTasksMax=128\n")
    if oom_hard:
        # Test twardego MemoryMax (OOM): wyłącz MemoryHigh, by throttling reclaimu nie opóźniał
        # alokacji poza RuntimeMaxSec. MemoryMax + MemorySwapMax=0 nadal wymuszają OOM. Presję
        # MemoryHigh weryfikują osobno wartości usługi produkcyjnej (main) i sonda memory-control.
        (drop / "91-oom.conf").write_text("[Service]\nMemoryHigh=infinity\n")
    unit_path.write_text(
        f"[Service]\nType=exec\nSlice={slice_name}\n"
        f"ExecStart=/usr/bin/python3 {script} {' '.join(args)}\n"
        "RuntimeMaxSec=45\nTimeoutStopSec=5\nRestart=no\n"
    )
    try:
        run("systemctl", "daemon-reload")
        run("systemctl", "start", slice_name)
        events_path = Path("/sys/fs/cgroup" + prop(slice_name, "ControlGroup")) / "memory.events"
        run("systemctl", "start", unit)
        deadline = time.monotonic() + 60
        while prop(unit, "ActiveState") not in {"inactive", "failed"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(unit)
            time.sleep(0.2)
        result = prop(unit, "Result"), prop(unit, "ExecMainStatus")
        if result[0] == "oom-kill":
            events = dict(line.split() for line in events_path.read_text().splitlines())
            assert int(events["oom"]) > 0 and int(events["oom_kill"]) > 0, events
        print(label, result, flush=True)
        if result[0] != "success":
            print(run("journalctl", "-u", unit, "--no-pager", "-n", "20"))
            # throttle (MemoryHigh) vs twardy OOM (MemoryMax): stan pamięci slice'a przed sprzątaniem
            for name in ("memory.events", "memory.current", "memory.peak", "memory.swap.current"):
                stat = events_path.parent / name
                if stat.is_file():
                    print(f"  {name}: {' '.join(stat.read_text().split())}", flush=True)
        return result
    finally:
        run("systemctl", "stop", unit)
        subprocess.run(["systemctl", "reset-failed", unit], check=False, capture_output=True, timeout=15)  # noqa: S603,S607
        run("systemctl", "stop", slice_name)
        slice_path.unlink()
        unit_path.unlink()
        shutil.rmtree(drop)
        run("systemctl", "daemon-reload")


def main(login: str) -> None:
    """LOGIN: istniejący login badacza bez prefiksu jupyter-; błąd asercji blokuje akceptację."""
    assert os.geteuid() == 0
    assert Path("/sys/fs/cgroup/cgroup.controllers").is_file(), "Wymagane cgroups v2"
    services = [SERVICE, "jupyterhub.service", "rsyslog.service", "auditd.service"]
    run("systemctl", "is-active", *services)
    before = {s: prop(s, "MainPID") for s in services}
    cg = Path("/sys/fs/cgroup" + prop(SERVICE, "ControlGroup"))
    assert cg != Path("/sys/fs/cgroup") and cg.is_dir()
    memory, tasks = int(prop(SERVICE, "MemoryMax")), int(prop(SERVICE, "TasksMax"))
    high = int(prop(SERVICE, "MemoryHigh"))
    assert 0 < high < memory
    for filename, expected in {
        "memory.max": memory,
        "memory.high": high,
        "memory.swap.max": 0,
        "pids.max": tasks,
    }.items():
        assert int((cg / filename).read_text()) == expected, filename
    assert prop(SERVICE, "Delegate") == "no"
    assert prop(SERVICE, "ProtectControlGroups") == "yes"
    assert prop(SERVICE, "OOMPolicy") == "stop"
    assert prop(SERVICE, "KillMode") == "control-group"
    assert prop(SERVICE, "Restart") == "always"
    assert f"default {prop(SERVICE, 'IOWeight')}" in (cg / "io.weight").read_text().splitlines()
    for path, operation in [
        (cg / "memory.max", str(memory)),
        (cg / "pids.max", str(tasks)),
        (cg / "cgroup.procs", "pid"),
        (cg, "chmod"),
    ]:
        run("sudo", "-u", f"jupyter-{login}", "python3", "-c", DENIED, str(path), operation)
    allocation, children = budget(memory, tasks)
    available = (
        int(
            next(
                line.split()[1]
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemAvailable:")
            )
        )
        * 1024
    )
    assert available >= 1024**3, "Brak 1 GiB zapasu dla ograniczonej kontroli; FAIL, nie SKIP"
    with tempfile.TemporaryDirectory(prefix="sluza-", dir="/run") as tmp:
        root = Path(tmp)
        assert probe(root, "memory", MEMORY, [str(allocation)], oom_hard=True) == ("oom-kill", "9")
        assert probe(root, "memory-control", MEMORY, [str(allocation)], control=True) == ("success", "0")
        assert probe(root, "tasks", FORK, [str(children), "blocked"]) == ("success", "0")
        assert probe(root, "tasks-control", FORK, [str(children), "allowed"], control=True) == ("success", "0")
        # Działający mover pod tym samym drop-in, prywatna kolejka i rzeczywiste hashowanie.
        source, queue = root / "out", root / "queue"
        source.mkdir()
        queue.mkdir()
        (source / "sample").write_bytes(b"x" * 1024**2)
        code = f"""import os, subprocess
os.environ.update(WLB_SLUZA_OUT={str(source)!r}, WLB_EXPORT_QUEUE={str(queue)!r}, WLB_IMAGE_CONF='/dev/null')
subprocess.run(['/usr/local/sbin/wlb-sluza-out-mover', '--once'], check=True)
"""
        assert probe(root, "mover", code, []) == ("success", "0")
        assert not list(source.iterdir())
        # Po #147 wpis kolejki to pakiet: katalog <ts>_<owner>_<nazwa>/ z payload + manifest.json,
        # nie surowy plik. Dotfiles (.mover.lock, .incoming.*) są wewnętrzne i niewidoczne dla badacza —
        # pomijamy je jak bats (ls bez -a). Weryfikujemy pakiet i payload (dla pojedynczego pliku to plik).
        entries = [e for e in queue.iterdir() if not e.name.startswith(".")]
        assert len(entries) == 1, entries
        pkg = entries[0]
        assert (pkg / "manifest.json").is_file(), list(pkg.iterdir())
        assert (pkg / "payload").read_bytes() == b"x" * 1024**2
    run("systemctl", "is-active", *services)
    assert before == {s: prop(s, "MainPID") for s in services}, "Usługa krytyczna zrestartowała się"


if __name__ == "__main__":
    main(sys.argv[1])
