#!/usr/bin/env python3
"""Przygotowanie raportów SARIF do publikacji w GitHub code scanning (#257).

Job skanujący nie ma uprawnień zapisu, więc cała walidacja i sanityzacja dzieje się
tutaj: sprawdzamy, że raport jest kompletnym SARIF 2.1.0 właściwego narzędzia, usuwamy
z niego fragmenty kodu (snippet/contextRegion), a wynik zapisujemy jako artefakt dla
osobnego joba publikującego. Ten job czyta już tylko gotowe pliki i manifest — nie
uruchamia żadnych skryptów z repozytorium.

Brak raportu nie jest tym samym co raport czysty: wynik ``not_run``/``error`` nigdy nie
jest publikowany, a plik wyjściowy przebiegu zakończonego błędem jest usuwany.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Report:
    """Opis jednego raportu SARIF oczekiwanego w katalogu SCA."""

    tool: str
    sarif: str
    category: str
    driver: str
    requires_rules: bool = False


REPORTS: dict[str, Report] = {
    "semgrep": Report(
        tool="semgrep",
        sarif="semgrep.sarif",
        category="semgrep",
        driver="semgrep",
        requires_rules=True,
    ),
    "checkov": Report(
        tool="checkov",
        sarif="checkov.sarif",
        category="checkov",
        driver="checkov",
        requires_rules=False,
    ),
}
OUTCOMES = ("clean", "findings", "error", "not_run")
MAX_GZIP_BYTES = 10 * 1024 * 1024  # limit GitHub dla uploadu (gzip)
MAX_RAW_BYTES = 100 * 1024 * 1024  # zanim w ogóle parsujemy
# GitHub od 07.2025 odrzuca plik z wieloma przebiegami tej samej kategorii; kategoria jest per upload
RUNS_PER_REPORT = 1
MAX_RESULTS_PER_RUN = 25_000
MAX_RULES_PER_RUN = 25_000

_RUN_ENV = (
    ("repository", "GITHUB_REPOSITORY"),
    ("sha", "GITHUB_SHA"),
    ("ref", "GITHUB_REF"),
    ("event", "GITHUB_EVENT_NAME"),
    ("run_id", "GITHUB_RUN_ID"),
    ("run_attempt", "GITHUB_RUN_ATTEMPT"),
)


class ReportError(Exception):
    """Raport nie nadaje się do publikacji; komunikat nigdy nie zawiera jego treści."""


@dataclass(frozen=True)
class ReportInfo:
    """Metadane przyjętego raportu, liczone już po sanityzacji.

    ``result_count`` to liczba aktywnych wyników (wyciszone ``# nosemgrep`` nie liczą się
    do klasyfikacji), a ``suppressed_count`` — liczba wyników wyciszonych.
    """

    tool: str
    category: str
    sha256: str
    result_count: int
    driver_version: str
    rules_digest: str
    suppressed_count: int = 0


def _expected(expected_tool: str) -> Report:
    try:
        return REPORTS[expected_tool]
    except KeyError as exc:
        raise ValueError(f"nieznane narzędzie: {expected_tool}") from exc


def _validate_run(run: object, expected: Report) -> None:
    if not isinstance(run, dict):
        raise ReportError(f"raport {expected.sarif} zawiera niepoprawny przebieg")
    tool = run.get("tool")
    driver = tool.get("driver") if isinstance(tool, dict) else None
    name = driver.get("name") if isinstance(driver, dict) else None
    if not isinstance(name, str) or expected.driver not in name.lower():
        raise ReportError(f"raport {expected.sarif} nie pochodzi z narzędzia {expected.tool}")
    invocations = run.get("invocations")
    if invocations is not None:
        if not isinstance(invocations, list):
            raise ReportError(f"raport {expected.sarif}: invocations nie jest listą")
        for invocation in invocations:
            if not isinstance(invocation, dict):
                raise ReportError(f"raport {expected.sarif}: element invocations nie jest obiektem")
            if invocation.get("executionSuccessful") is False:
                raise ReportError("skaner zgłosił nieudane wykonanie")
            for key in ("toolExecutionNotifications", "toolConfigurationNotifications"):
                notifications = invocation.get(key)
                if notifications is not None:
                    if not isinstance(notifications, list):
                        raise ReportError(f"raport {expected.sarif}: {key} nie jest listą")
                    for notification in notifications:
                        if not isinstance(notification, dict):
                            raise ReportError(f"raport {expected.sarif}: notyfikacja nie jest obiektem")
                        if notification.get("level") == "error":
                            raise ReportError(
                                "skaner zgłosił błąd wykonania (notyfikacja level=error) — analiza niekompletna"
                            )
    if "results" in run:
        results = run["results"]
        if not isinstance(results, list):
            raise ReportError(f"raport {expected.sarif}: results nie jest listą")
        if len(results) > MAX_RESULTS_PER_RUN:
            raise ReportError(f"raport {expected.sarif} ma zbyt wiele wyników")
        if not all(isinstance(result, dict) for result in results):
            raise ReportError(f"raport {expected.sarif}: wynik nie jest obiektem")
    rules = driver.get("rules")
    if rules is not None:
        if not isinstance(rules, list):
            raise ReportError(f"raport {expected.sarif}: rules nie jest listą")
        if len(rules) > MAX_RULES_PER_RUN:
            raise ReportError(f"raport {expected.sarif} ma zbyt wiele reguł")
        if not all(isinstance(rule, dict) for rule in rules):
            raise ReportError(f"raport {expected.sarif}: reguła nie jest obiektem")


def load_report(path: Path, expected_tool: str) -> dict:
    """Wczytuje i waliduje SARIF 2.1.0 wskazanego narzędzia; błąd -> ReportError."""
    path = Path(path)
    expected = _expected(expected_tool)
    if path.is_symlink():
        raise ReportError(f"raport {expected.sarif} jest dowiązaniem symbolicznym")
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise ReportError(f"brak raportu {expected.sarif}") from exc
    except OSError as exc:
        raise ReportError(f"nie można odczytać raportu {expected.sarif}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise ReportError(f"raport {expected.sarif} nie jest zwykłym plikiem")
    if st.st_size > MAX_RAW_BYTES:
        raise ReportError(f"raport {expected.sarif} przekracza limit rozmiaru")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReportError(f"raport {expected.sarif} nie jest poprawnym UTF-8") from exc
    except OSError as exc:
        raise ReportError(f"nie można odczytać raportu {expected.sarif}") from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportError(f"raport {expected.sarif} nie jest poprawnym JSON") from exc
    if not isinstance(doc, dict):
        raise ReportError(f"raport {expected.sarif} nie jest obiektem JSON")
    if doc.get("version") != "2.1.0":
        raise ReportError(f"raport {expected.sarif} nie jest w wersji SARIF 2.1.0")
    runs = doc.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ReportError(f"raport {expected.sarif} nie zawiera przebiegów")
    if len(runs) != RUNS_PER_REPORT:
        raise ReportError(f"raport {expected.sarif} musi mieć dokładnie jeden przebieg (jedna kategoria)")
    for run in runs:
        _validate_run(run, expected)
    if expected.requires_rules:
        total_rules = sum(len(run["tool"]["driver"].get("rules") or []) for run in runs)
        if total_rules == 0:
            raise ReportError(f"raport {expected.sarif} nie zawiera reguł")
    return doc


def _rule_text(rule: dict | None, rule_id: str) -> str:
    """Wyznacza bezpieczny tekst opisu wyniku na podstawie reguły (nigdy z result.message)."""
    if isinstance(rule, dict):
        short = rule.get("shortDescription")
        if isinstance(short, dict):
            text = short.get("text")
            if isinstance(text, str) and text.strip():
                return text[:500]
        full = rule.get("fullDescription")
        if isinstance(full, dict):
            text = full.get("text")
            if isinstance(text, str) and text.strip():
                return text[:500]
        name = rule.get("name")
        if isinstance(name, str) and name.strip():
            return name[:500]
    return rule_id[:500]


def _export_rule(rule: dict) -> dict | None:
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        return None
    item: dict = {"id": rule_id}
    name = rule.get("name")
    if isinstance(name, str) and name:
        item["name"] = name
    short = rule.get("shortDescription")
    if isinstance(short, dict) and isinstance(short.get("text"), str):
        item["shortDescription"] = {"text": short["text"]}
    full = rule.get("fullDescription")
    if isinstance(full, dict) and isinstance(full.get("text"), str):
        item["fullDescription"] = {"text": full["text"]}
    help_obj = rule.get("help")
    if isinstance(help_obj, dict):
        h_dict: dict[str, str] = {}
        if isinstance(help_obj.get("text"), str):
            h_dict["text"] = help_obj["text"]
        if isinstance(help_obj.get("markdown"), str):
            h_dict["markdown"] = help_obj["markdown"]
        if h_dict:
            item["help"] = h_dict
    help_uri = rule.get("helpUri")
    if isinstance(help_uri, str) and help_uri:
        item["helpUri"] = help_uri
    default_config = rule.get("defaultConfiguration")
    if isinstance(default_config, dict):
        level = default_config.get("level")
        if isinstance(level, str) and level in {"none", "note", "warning", "error"}:
            item["defaultConfiguration"] = {"level": level}
    props = rule.get("properties")
    if isinstance(props, dict):
        p_dict: dict = {}
        tags = props.get("tags")
        if isinstance(tags, list):
            safe_tags = [t for t in tags if isinstance(t, str)]
            if safe_tags:
                p_dict["tags"] = safe_tags
        prec = props.get("precision")
        if isinstance(prec, str) and prec:
            p_dict["precision"] = prec
        sec_sev = props.get("security-severity")
        if isinstance(sec_sev, str) and sec_sev:
            p_dict["security-severity"] = sec_sev
        elif isinstance(sec_sev, (int, float)) and not isinstance(sec_sev, bool):
            p_dict["security-severity"] = str(sec_sev)
        prob_sev = props.get("problem.severity")
        if isinstance(prob_sev, str) and prob_sev:
            p_dict["problem.severity"] = prob_sev
        if p_dict:
            item["properties"] = p_dict
    return item


def _export_notification(notification: dict) -> dict:
    descriptor = notification.get("descriptor")
    desc_id = descriptor.get("id") if isinstance(descriptor, dict) else None
    ident = desc_id[:80] if isinstance(desc_id, str) and desc_id else "komunikat narzędzia"
    item: dict = {"message": {"text": f"{ident} (szczegóły: skan lokalny, make security)"}}
    if isinstance(desc_id, str) and desc_id:
        item["descriptor"] = {"id": desc_id}
    level = notification.get("level")
    if isinstance(level, str) and level in {"none", "note", "warning", "error"}:
        item["level"] = level
    return item


def _export_location(loc: object) -> dict | None:
    if not isinstance(loc, dict):
        return None
    phys = loc.get("physicalLocation")
    if not isinstance(phys, dict):
        return None
    art = phys.get("artifactLocation")
    if not isinstance(art, dict):
        return None
    uri = art.get("uri")
    if not isinstance(uri, str) or not uri:
        return None
    region = phys.get("region")
    if not isinstance(region, dict):
        return None
    start_line = region.get("startLine")
    if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
        return None

    art_dict: dict[str, str] = {"uri": uri}
    uri_base_id = art.get("uriBaseId")
    if isinstance(uri_base_id, str) and uri_base_id:
        art_dict["uriBaseId"] = uri_base_id

    reg_dict: dict[str, int] = {"startLine": start_line}
    for col_key in ("startColumn", "endLine", "endColumn"):
        val = region.get(col_key)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 1:
            reg_dict[col_key] = val

    return {
        "physicalLocation": {
            "artifactLocation": art_dict,
            "region": reg_dict,
        }
    }


def _export_result(
    result: object,
    rules_map: dict[str, dict],
    rules_list: list[dict],
) -> dict:
    if not isinstance(result, dict):
        raise ReportError("wynik nie jest obiektem")
    rule_id = result.get("ruleId")
    if not isinstance(rule_id, str) or not rule_id:
        raise ReportError("wynik bez reguły lub lokalizacji")

    locations = result.get("locations")
    if not isinstance(locations, list) or not locations:
        raise ReportError("wynik bez reguły lub lokalizacji")

    valid_locations: list[dict] = []
    for loc in locations:
        exported_loc = _export_location(loc)
        if exported_loc is not None:
            valid_locations.append(exported_loc)

    if not valid_locations:
        raise ReportError("wynik bez reguły lub lokalizacji")

    rule = rules_map.get(rule_id)
    rule_index = result.get("ruleIndex")
    if (
        rule is None
        and isinstance(rule_index, int)
        and not isinstance(rule_index, bool)
        and 0 <= rule_index < len(rules_list)
    ):
        rule = rules_list[rule_index]

    res_item: dict = {
        "ruleId": rule_id,
        "message": {"text": _rule_text(rule, rule_id)},
        "locations": valid_locations,
    }
    # ruleIndex nie jest eksportowany: eksport pomija reguły bez id, więc indeks mógłby wskazać inną regułę
    level = result.get("level")
    if isinstance(level, str) and level in {"none", "note", "warning", "error"}:
        res_item["level"] = level
    pfp = result.get("partialFingerprints")
    if isinstance(pfp, dict):
        safe_pfp = {k: v for k, v in pfp.items() if isinstance(k, str) and isinstance(v, str)}
        if safe_pfp:
            res_item["partialFingerprints"] = safe_pfp
    return res_item


def export_sarif(doc: dict) -> dict:
    """Eksportuje bezpieczny dokument SARIF 2.1.0 na podstawie ścisłej allowlisty pól.

    Usuwa wszelkie fragmenty kodu źródłowego (snippet, contextRegion, relatedLocations,
    codeFlows, stacks, fixes itp.), metazmienne z treści komunikatów wyników (zastępowane
    bezpiecznym opisem właściwej reguły) oraz nieobsługiwane pola (fingerprints, suppressions).
    Notyfikacje wykonania są zastępowane identyfikatorem i ogólną wskazówką naprawy.
    Nie przenosi też ``ruleIndex`` (indeksy po odrzuceniu reguł bez id byłyby przesunięte) ani
    ``automationDetails`` (kategorię ustala wyłącznie workflow, nie treść raportu).
    """
    exported_runs: list[dict] = []
    runs = doc.get("runs") if isinstance(doc, dict) else None
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        tool = run.get("tool")
        driver = tool.get("driver") if isinstance(tool, dict) else None
        driver_name = driver.get("name") if isinstance(driver, dict) else None
        driver_dict: dict = {"name": driver_name if isinstance(driver_name, str) else ""}
        if isinstance(driver, dict):
            version = driver.get("version")
            if isinstance(version, str) and version:
                driver_dict["version"] = version
            semantic_version = driver.get("semanticVersion")
            if isinstance(semantic_version, str) and semantic_version:
                driver_dict["semanticVersion"] = semantic_version
            info_uri = driver.get("informationUri")
            if isinstance(info_uri, str) and info_uri:
                driver_dict["informationUri"] = info_uri

        raw_rules = driver.get("rules") if isinstance(driver, dict) else None
        rules_list: list[dict] = []
        rules_map: dict[str, dict] = {}
        exported_rules: list[dict] = []
        if isinstance(raw_rules, list):
            for r in raw_rules:
                if isinstance(r, dict):
                    rules_list.append(r)
                    rid = r.get("id")
                    if isinstance(rid, str) and rid:
                        rules_map[rid] = r
                    exported_rule = _export_rule(r)
                    if exported_rule is not None:
                        exported_rules.append(exported_rule)
        driver_dict["rules"] = exported_rules

        exported_results: list[dict] = []
        raw_results = run.get("results")
        if isinstance(raw_results, list):
            for res in raw_results:
                exported_results.append(_export_result(res, rules_map, rules_list))

        run_dict: dict = {
            "tool": {"driver": driver_dict},
            "results": exported_results,
        }
        # automationDetails nie jest eksportowany: kategorię ustala wyłącznie workflow (wejście category)

        exported_invocations: list[dict] = []
        invocations = run.get("invocations")
        if isinstance(invocations, list):
            for invocation in invocations:
                if not isinstance(invocation, dict):
                    continue
                inv_item: dict = {}
                if "executionSuccessful" in invocation and isinstance(invocation["executionSuccessful"], bool):
                    inv_item["executionSuccessful"] = invocation["executionSuccessful"]
                raw_notifs = invocation.get("toolExecutionNotifications")
                if isinstance(raw_notifs, list):
                    notifs = [_export_notification(n) for n in raw_notifs if isinstance(n, dict)]
                    if notifs:
                        inv_item["toolExecutionNotifications"] = notifs
                if inv_item:
                    exported_invocations.append(inv_item)

        if exported_invocations:
            run_dict["invocations"] = exported_invocations

        exported_runs.append(run_dict)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": exported_runs,
    }


def _is_suppressed(result: object) -> bool:
    """Wynik wyciszony: suppressions to niepusta lista poprawnych wpisów (kind + accepted/brak statusu)."""
    if not isinstance(result, dict):
        return False
    suppressions = result.get("suppressions")
    if not isinstance(suppressions, list) or not suppressions:
        return False
    for item in suppressions:
        if not isinstance(item, dict):
            return False
        if item.get("kind") not in ("inSource", "external"):
            return False
        status = item.get("status")
        if status is not None and status != "accepted":
            return False
    return True


def classify(exit_code: int | None, info: ReportInfo | None) -> str:
    """Klasyfikuje przebieg skanera: clean/findings/error/not_run."""
    if exit_code is None:
        return "not_run"
    if info is None:
        return "error"
    if exit_code == 0:
        return "clean" if info.result_count == 0 else "findings"
    if exit_code == 1 and info.result_count > 0:
        return "findings"
    return "error"


def read_exit_code(path: Path) -> int | None:
    """Kod wyjścia skanera: brak pliku -> None, istniejący lecz niepoprawny -> -1."""
    path = Path(path)
    try:
        if path.is_symlink():
            return -1
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        return -1
    if not stat.S_ISREG(st.st_mode):
        return -1
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return -1
    if not text:
        return -1
    try:
        return int(text)
    except ValueError:
        return -1


def drop_suppressed(doc: dict) -> dict:
    """Zwraca kopię raportu bez wyników wyciszonych w kodzie (``# nosemgrep``, ``checkov:skip``).

    GitHub Code scanning ignoruje pole ``suppressions`` i pokazałby takie wyniki jako otwarte alerty,
    choć bramka etapu 3 ich nie liczy, a uzasadnienie jest w kodzie. Liczbę wyciszeń zachowuje manifest.
    """
    kept = copy.deepcopy(doc)
    for run in kept.get("runs") or []:
        if isinstance(run, dict) and isinstance(run.get("results"), list):
            run["results"] = [result for result in run["results"] if not _is_suppressed(result)]
    return kept


def _report_info(report: Report, doc: dict, payload: bytes) -> ReportInfo:
    """Metadane liczone z raportu wejściowego przed usunięciem wyciszeń (liczniki) i payloadu."""
    runs = doc["runs"]
    results = [result for run in runs for result in (run.get("results") or [])]
    suppressed_count = sum(1 for result in results if _is_suppressed(result))
    result_count = len(results) - suppressed_count
    rules = [run["tool"]["driver"].get("rules") or [] for run in runs]
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    driver_version = ""
    for run in runs:
        driver = run["tool"]["driver"]
        # checkov: version; semgrep: tylko semanticVersion
        version = driver.get("version") or driver.get("semanticVersion")
        if isinstance(version, str) and version:
            driver_version = version
            break
    return ReportInfo(
        tool=report.tool,
        category=report.category,
        sha256=hashlib.sha256(payload).hexdigest(),
        result_count=result_count,
        driver_version=driver_version,
        rules_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        suppressed_count=suppressed_count,
    )


def _prepare_report(report: Report, source: Path, target: Path) -> ReportInfo:
    """Waliduje, sanityzuje i zapisuje raport; przy błędzie nie zostawia pliku."""
    try:
        doc = load_report(source, report.tool)
        clean = drop_suppressed(doc)
        exported = export_sarif(clean)
        payload = json.dumps(exported, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        target.write_bytes(payload)
        if len(gzip.compress(payload)) > MAX_GZIP_BYTES:
            raise ReportError(f"raport {report.sarif} przekracza limit rozmiaru gzip")
        return _report_info(report, doc, payload)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ReportError(f"nie udało się zapisać raportu {report.sarif}") from exc
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _mismatch_reason(exit_code: int) -> str:
    if exit_code == 1:
        return "kod wyjścia 1, ale raport nie zawiera wyników"
    return f"kod wyjścia skanera {exit_code} oznacza błąd narzędzia"


def _run_metadata(env: Mapping[str, str]) -> dict[str, str]:
    return {key: str(env.get(name) or "") for key, name in _RUN_ENV}


def _publish_label(entry: dict) -> str:
    if entry["publish"]:
        return "tak"
    reason = entry.get("reason")
    return f"nie — {reason}" if reason else "nie"


def _summary_table(entries: list[dict]) -> str:
    lines = [
        "### Raporty SARIF dla Code scanning (#257)",
        "",
        "| Narzędzie | Kategoria | Wynik skanu | Wyników | Wersja | Reguły | Publikacja |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        rules = entry.get("rules_digest")
        lines.append(
            f"| {entry['tool']} | {entry['category']} | {entry['outcome']} | "
            f"{entry.get('result_count', '—')} | {entry.get('driver_version') or '—'} | "
            f"{rules[:12] if rules else '—'} | {_publish_label(entry)} |"
        )
    return "\n".join(lines) + "\n"


def _append_github_output(path: str, entries: list[dict]) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(f"{entry['tool']}={entry['outcome']}\n")


def _write_summary(env: Mapping[str, str], entries: list[dict]) -> None:
    table = _summary_table(entries)
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as fh:
            fh.write(table)
    else:
        sys.stdout.write(table)


def prepare(sca_dir: Path, out_dir: Path, env: Mapping[str, str]) -> dict:
    """Przygotowuje artefakty code scanning i zwraca manifest."""
    sca_dir = Path(sca_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in (*[report.sarif for report in REPORTS.values()], "manifest.json"):
        (out_dir / name).unlink(missing_ok=True)

    entries: list[dict] = []
    for tool, report in REPORTS.items():
        exit_code = read_exit_code(sca_dir / f"{tool}.exit")
        target = out_dir / report.sarif
        info: ReportInfo | None = None
        reason: str | None = None
        if exit_code is None:
            outcome = "not_run"
        elif exit_code not in (0, 1):
            # awaria narzędzia (np. semgrep 7 = zła konfiguracja): powód z kodu wyjścia, nie ze struktury
            # częściowego raportu — taki raport i tak nie jest publikowany
            outcome = "error"
            reason = _mismatch_reason(exit_code)
        else:
            try:
                info = _prepare_report(report, sca_dir / report.sarif, target)
            except ReportError as exc:
                outcome = "error"
                reason = str(exc)
            else:
                outcome = classify(exit_code, info)
                if outcome == "error":
                    target.unlink(missing_ok=True)
                    reason = _mismatch_reason(exit_code)

        entry: dict = {
            "tool": report.tool,
            "category": report.category,
            "outcome": outcome,
            "publish": outcome in ("clean", "findings"),
            "exit_code": exit_code,
        }
        if reason is not None:
            entry["reason"] = reason
        if entry["publish"] and info is not None:
            entry["sha256"] = info.sha256
            entry["result_count"] = info.result_count
            entry["suppressed_count"] = info.suppressed_count
            entry["driver_version"] = info.driver_version
            entry["rules_digest"] = info.rules_digest
        entries.append(entry)

    manifest = {"schema": 1, "run": _run_metadata(env), "reports": entries}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    output = env.get("GITHUB_OUTPUT")
    if output:
        _append_github_output(output, entries)
    _write_summary(env, entries)
    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI: ``prepare --sca-dir PATH --out-dir PATH``; 2 tylko przy błędzie użycia."""
    parser = argparse.ArgumentParser(description="Przygotowuje raporty SARIF do publikacji (#257).")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare", help="waliduje i sanityzuje raporty SARIF")
    command.add_argument("--sca-dir", type=Path, required=True)
    command.add_argument("--out-dir", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    prepare(args.sca_dir, args.out_dir, os.environ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
