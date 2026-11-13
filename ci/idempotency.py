#!/usr/bin/env python3
"""Bramka idempotencji Ansible (#288, klasa 3): drugi przebieg playbooka musi dać changed=0.

Czyta log `ansible-playbook` (callback yaml) i sprawdza PLAY RECAP:
changed=0, failed=0, unreachable=0. Przy changed>0 wypisuje nazwy tasków, które raportowały
zmianę (z sekcji `TASK [...]`), żeby poprawka była wskazywana, a nie zgadywana.

Kody wyjścia: 0 = idempotentnie, 1 = changed/failed/unreachable > 0, 2 = brak PLAY RECAP
(playbook nie doszedł do końca — to też błąd bramki).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RECAP = re.compile(
    r"^(?P<host>\S+)\s*:\s*ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+"
    r"unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)",
    re.MULTILINE,
)
TASK = re.compile(r"^TASK \[(?P<name>.+?)\]", re.MULTILINE)
CHANGED = re.compile(r"^changed: \[(?P<host>[^\]]+)\]", re.MULTILINE)


def parse(text: str) -> dict[str, object]:
    """Zwraca recap per host + nazwy tasków, które zgłosiły changed."""
    recaps = [
        {
            "host": m.group("host"),
            "ok": int(m.group("ok")),
            "changed": int(m.group("changed")),
            "unreachable": int(m.group("unreachable")),
            "failed": int(m.group("failed")),
        }
        for m in RECAP.finditer(text)
    ]
    changed_tasks: list[str] = []
    current = None
    for line in text.splitlines():
        m = TASK.match(line)
        if m:
            current = m.group("name")
            continue
        if CHANGED.match(line) and current and current not in changed_tasks:
            changed_tasks.append(current)
    return {
        "recaps": recaps,
        "changed": sum(r["changed"] for r in recaps),
        "failed": sum(r["failed"] for r in recaps),
        "unreachable": sum(r["unreachable"] for r in recaps),
        "changed_tasks": changed_tasks,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("użycie: idempotency.py LOG", file=sys.stderr)
        return 2
    log = Path(argv[1])
    if not log.is_file():
        print(f"BŁĄD: brak logu {log}", file=sys.stderr)
        return 2
    result = parse(log.read_text(encoding="utf-8", errors="replace"))
    if not result["recaps"]:
        print("BŁĄD: brak PLAY RECAP — playbook nie doszedł do końca", file=sys.stderr)
        return 2
    for r in result["recaps"]:
        print(
            f"RECAP {r['host']}: ok={r['ok']} changed={r['changed']} "
            f"unreachable={r['unreachable']} failed={r['failed']}"
        )
    problems = []
    if result["changed"]:
        problems.append(f"changed={result['changed']}")
        for task in result["changed_tasks"]:
            print(f"ZMIANA: {task}")
        if not result["changed_tasks"]:
            print("ZMIANA: (nie udało się przypisać changed do nazwy tasku — zajrzyj do logu)")
    if result["failed"]:
        problems.append(f"failed={result['failed']}")
    if result["unreachable"]:
        problems.append(f"unreachable={result['unreachable']}")
    if problems:
        print(
            f"BŁĄD idempotencji (#288): drugi przebieg nie jest no-op — {', '.join(problems)} (log: {log})",
            file=sys.stderr,
        )
        return 1
    print("OK: drugi przebieg playbooka jest idempotentny (changed=0)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
