#!/usr/bin/env bash
# Verify the pre_delete_guard guardrail blocks destructive commands (file-safety).
# A blocked call must exit 2.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HOOK="${ROOT}/.claude/hooks/pre_delete_guard.py"
PASS=0
FAIL=0

check() {
  local label="$1" expected="$2" payload="$3"
  local actual
  echo "${payload}" | python "${HOOK}" > /dev/null 2>&1
  actual=$?
  if [[ "${actual}" == "${expected}" ]]; then
    echo "  PASS  ${label} (exit ${actual})"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${label} - expected exit ${expected}, got ${actual}"
    FAIL=$((FAIL + 1))
  fi
}

echo "pre_delete_guard.py - must BLOCK (exit 2):"
check "rm -rf outside projects"   2 '{"tool_name":"Bash","tool_input":{"command":"rm -rf /etc/important"}}'
check "rm -rf home"               2 '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~/Documents"}}'
check "rm -fr flag order"         2 '{"tool_name":"Bash","tool_input":{"command":"rm -fr ../other"}}'
check "rm inside pricebooks"      2 '{"tool_name":"Bash","tool_input":{"command":"rm pricebooks/hager_price_book_18.pdf"}}'
check "rm inside reference-library" 2 '{"tool_name":"Bash","tool_input":{"command":"rm reference-library/margins/margin_framework.json"}}'
check "git push"                  2 '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'

# The three bypasses the audit found, each verified against a control that was
# already blocked. Every one of these exited 0 before.
check "heredoc hides its redirect" 2 '{"tool_name":"Bash","tool_input":{"command":"cat <<EOF > pricebooks/vendor.csv\nnew,data\nEOF"}}'
check "separated rm flags"         2 '{"tool_name":"Bash","tool_input":{"command":"rm -r -f /etc/important"}}'
check "long rm flags"              2 '{"tool_name":"Bash","tool_input":{"command":"rm --recursive --force /etc/important"}}'
check "a comment naming projects/" 2 '{"tool_name":"Bash","tool_input":{"command":"rm -rf /etc/important # projects/"}}'

echo
echo "pre_delete_guard.py - must ALLOW (exit 0):"
check "rm -rf inside projects" 0 '{"tool_name":"Bash","tool_input":{"command":"rm -rf projects/demo/uploads/processed"}}'
check "read a price book"      0 '{"tool_name":"Bash","tool_input":{"command":"cat pricebooks/index.json"}}'
check "list files"             0 '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}'
check "git status"             0 '{"tool_name":"Bash","tool_input":{"command":"git status"}}'
# The stripper still has to let documentation through - that is why it exists.
check "heredoc documenting the rule" 0 '{"tool_name":"Bash","tool_input":{"command":"cat <<EOF > projects/demo/notes.md\nnever rm -rf pricebooks/\nEOF"}}'

echo
if [[ "${FAIL}" -gt 0 ]]; then
  echo "GUARDRAIL FAILURE: ${FAIL} failed, ${PASS} passed. Do NOT run the pipeline unattended."
  exit 1
fi
echo "OK - ${PASS} checks passed. Destructive commands are blocked (file-safety)."
