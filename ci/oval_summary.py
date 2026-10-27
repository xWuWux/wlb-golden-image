#!/usr/bin/env python3
"""Podsumowanie skanu OVAL Canonical (USN) obrazu (#3, wariant C).

Argumenty: <dpkg-status> <oval.xml> <oscap-results.xml>

Markdown:
  1. Świeżość jądra — najwyższe ABI linux-image-<seria>-NNN-generic w danych USN vs zainstalowane.
     oscap NIE flaguje jądra (USN kluczują poprawki na wersjonowanych pakietach binarnych), więc ten
     sygnał liczymy z samych danych OVAL przez porównanie wersji.
  2. Podatne definicje (oscap result="true") — pakiety NIE-jądrowe z dostępną poprawką (USN).

Parsujemy regexem (nie XML), bo interesują nas pojedyncze tokeny, a dane bywają duże (OVAL ~35 MB).
"""

import re
import sys


def installed_kernel_abi(dpkg_status):
    """Seria i ABI jądra z pakietu meta linux-image-virtual, np. ('6.8.0', 142)."""
    ver, pkg = None, None
    with open(dpkg_status, errors="replace") as f:
        for line in f:
            if line.startswith("Package: "):
                pkg = line[9:].strip()
            elif line.startswith("Version: ") and pkg == "linux-image-virtual":
                ver = line[9:].strip()
    m = re.match(r"(\d+\.\d+\.\d+)-(\d+)", ver or "")
    return (m.group(1), int(m.group(2))) if m else (None, None)


def max_oval_abi(oval_xml, series):
    """Najwyższe ABI linux-image-<seria>-NNN-generic w danych USN (= najnowsze załatane jądro)."""
    pat = re.compile(rf"linux-image-{re.escape(series)}-(\d+)-generic")
    with open(oval_xml, errors="replace") as f:
        nums = [int(x) for x in pat.findall(f.read())]
    return max(nums) if nums else -1


def count_vulnerable(results_xml):
    """Liczba definicji USN z wynikiem true (podatny) — pakiety nie-jądrowe (oscap eval)."""
    with open(results_xml, errors="replace") as f:
        return len(re.findall(r'<definition [^>]*result="true"', f.read()))


def main():
    dpkg, oval, results = sys.argv[1], sys.argv[2], sys.argv[3]
    series, inst = installed_kernel_abi(dpkg)
    out = ["### Skan OVAL Canonical (USN) obrazu", ""]
    if series:
        newest = max_oval_abi(oval, series)
        if newest > inst:
            out.append(
                f"- ⚠️ **Jądro: dostępne nowsze załatane** — zainstalowane `{series}-{inst}`, "
                f"najnowsze w USN `{series}-{newest}`. **Przebuduj obraz** (nowe CVE jądra z poprawką)."
            )
        else:
            out.append(f"- ✅ Jądro aktualne — zainstalowane `{series}-{inst}`, najnowsze w USN `{series}-{newest}`.")
    else:
        out.append("- (nie wykryto wersji jądra z dpkg-status)")
    out.append(f"- Podatne definicje USN (oscap, pakiety nie-jądrowe): **{count_vulnerable(results)}**")
    print("\n".join(out))


if __name__ == "__main__":
    main()
