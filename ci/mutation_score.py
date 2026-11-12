"""Ocena wyniku mutmut dla etapu 4b (ci/mutation.sh) — wydzielona, żeby miała testy.

Mianownik progu: `killed + unlisted`. Mutanty z allowlisty są równoważne z definicji, więc nie
zaniżają wyniku; `no tests` nie wchodzi (globalny próg pokrycia etapu 4 nie pilnuje pojedynczego
pliku). Każdy przeżyty mutant spoza allowlisty to twardy błąd, a wpis allowlisty bez uzasadnienia
po `#` też jest błędem. Nieaktualne wpisy allowlisty są tylko ostrzeżeniem.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

KNOWN = frozenset({"killed", "survived", "no tests", "timeout"})


def parse_results(text: str) -> dict[str, list[str]]:
    """`mutmut results --all true` -> {status: [nazwa mutanta, ...]}."""
    statuses: dict[str, list[str]] = {}
    for line in text.splitlines():
        if ": " not in line:
            continue
        name, status = line.rsplit(": ", 1)
        statuses.setdefault(status.strip(), []).append(name.strip())
    return statuses


def load_allowlist(path: Path) -> tuple[set[str], list[str]]:
    """Wpisy allowlisty + błędy (wpis bez uzasadnienia po `#`)."""
    allowed: set[str] = set()
    errors: list[str] = []
    if not path.is_file():
        return allowed, errors
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        name, _, reason = raw.partition("#")
        name = name.strip()
        if not name:
            continue
        if not reason.strip():
            errors.append(f"{path}:{number}: brak uzasadnienia po #")
        allowed.add(name)
    return allowed, errors


@dataclass
class Score:
    killed: int = 0
    survived: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    no_tests: int = 0
    timeouts: int = 0
    unknown: dict[str, int] = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)
    allowlist_errors: list[str] = field(default_factory=list)

    @property
    def scored(self) -> int:
        return self.killed + len(self.unlisted)

    @property
    def percent(self) -> float:
        return 100.0 * self.killed / self.scored if self.scored else 0.0

    def failures(self, minimum: float) -> list[str]:
        out: list[str] = []
        if self.allowlist_errors:
            out.append("Allowlista bez uzasadnienia:\n" + "\n".join(self.allowlist_errors))
        if self.scored == 0:
            out.append("Brak mutantów w zakresie — sprawdź sekcję [mutmut] w setup.cfg")
        if self.unknown:
            detail = ", ".join(f"{status}={count}" for status, count in sorted(self.unknown.items()))
            out.append(f"Nieznane statusy mutmut ({detail}) — nie mogą po cichu wypadać z progu")
        if self.timeouts:
            out.append(f"{self.timeouts} mutantów przekroczyło timeout — testy się zawieszają")
        if self.unlisted:
            out.append(f"{len(self.unlisted)} przeżyłych mutantów spoza allowlisty — dopisz test albo uzasadnij wpis")
        if self.scored and self.percent < minimum:
            out.append(f"Wynik mutacji {self.percent:.1f}% < {minimum:g}%")
        return out


def evaluate(statuses: dict[str, list[str]], allowed: set[str], allowlist_errors: list[str]) -> Score:
    survived = statuses.get("survived", [])
    return Score(
        killed=len(statuses.get("killed", [])),
        survived=survived,
        allowed=[name for name in survived if name in allowed],
        unlisted=[name for name in survived if name not in allowed],
        no_tests=len(statuses.get("no tests", [])),
        timeouts=len(statuses.get("timeout", [])),
        unknown={status: len(names) for status, names in statuses.items() if status not in KNOWN},
        stale=sorted(allowed - set(survived)),
        allowlist_errors=allowlist_errors,
    )


def render(score: Score, minimum: float) -> str:
    lines = [
        "### Mutacje Pythona (mutmut, `ci/verify_platform_images.py`)",
        "",
        "| Zabite | Przeżyły | z allowlisty | spoza allowlisty | Bez testów | Timeout | Wynik | Próg |",
        "|---|---|---|---|---|---|---|---|",
        f"| {score.killed} | {len(score.survived)} | {len(score.allowed)} | {len(score.unlisted)} | "
        f"{score.no_tests} | {score.timeouts} | **{score.percent:.1f}%** | {minimum:g}% |",
        "",
    ]
    if score.unlisted:
        lines += ["Przeżyłe mutanty **spoza allowlisty** (dopisz test albo uzasadnij w allowliście):", ""]
        lines += [f"- `{name}`" for name in score.unlisted]
        lines.append("")
    if score.allowed:
        lines += ["Przeżyłe mutanty z allowlisty (równoważne):", ""]
        lines += [f"- `{name}`" for name in score.allowed]
        lines.append("")
    if score.stale:
        lines += ["Allowlista nieaktualna — te mutanty już nie przeżywają (usuń wpisy):", ""]
        lines += [f"- `{name}`" for name in score.stale]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="wyjście mutmut results --all true")
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--minimum", type=float, default=85.0)
    parser.add_argument("--summary", type=Path, help="zapisz markdown tutaj")
    args = parser.parse_args(argv)

    allowed, allowlist_errors = load_allowlist(args.allowlist)
    score = evaluate(parse_results(args.results.read_text()), allowed, allowlist_errors)
    text = render(score, args.minimum)
    print(text)
    if args.summary:
        args.summary.write_text(text)
    for message in score.failures(args.minimum):
        print(f"BŁĄD: {message}", file=sys.stderr)
    return 1 if score.failures(args.minimum) else 0


if __name__ == "__main__":
    sys.exit(main())
