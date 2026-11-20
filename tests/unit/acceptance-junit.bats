#!/usr/bin/env bats
# #349 A1: JUnit XML emitowany obok historycznego stdout harnessu akceptacji.
# Test nie uruchamia VM; sprawdza rejestrator i finalizację XML w remote-common.sh.

load helpers

setup() {
  export WLB_JUNIT_TMP="$BATS_TEST_TMPDIR/junit.xml"
  export WLB_JUNIT_OUT="$BATS_TEST_TMPDIR/acceptance.xml"
  export REPO_ROOT
}

@test "acceptance JUnit: PASS/FAIL/SKIP, escaping, duplikaty i liczniki" {
  run bash -c '
    source "$REPO_ROOT/tests/lib/remote-common.sh"
    ok "pass & < > \""
    ko "fail & < > \""
    skip "skip reason"
    ok "dup"
    ok "dup"
    expect_ok "expect pass" true
    expect_fail "expect fail" false
    junit_finalize
  '
  [ "$status" -eq 0 ]
  [ -f "$WLB_JUNIT_OUT" ]

  python3 - "$WLB_JUNIT_OUT" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
assert root.tag == "testsuite", root.tag
assert root.get("name") == "acceptance-stage5"
assert root.get("tests") == "7", root.get("tests")
assert root.get("failures") == "1", root.get("failures")
assert root.get("skipped") == "1", root.get("skipped")
assert root.get("time", "").endswith(".000")

cases = root.findall("testcase")
names = [case.get("name") for case in cases]
assert "pass & < > \"" in names, names
assert "fail & < > \"" in names, names
assert "skip reason" in names, names
assert "dup" in names and "dup #2" in names, names
assert "expect pass" in names and "expect fail" in names, names

by_name = {case.get("name"): case for case in cases}
failure = by_name["fail & < > \""].find("failure")
assert failure is not None
assert failure.get("message") == "fail & < > \""
skipped = by_name["skip reason"].find("skipped")
assert skipped is not None
assert skipped.get("message") == "skip reason"
PY
}
