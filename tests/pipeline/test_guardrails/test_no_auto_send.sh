#!/usr/bin/env bash
# Verify the pre_send_quote guardrail blocks every send path (NFR-1).
# A blocked call must exit 2. Anything else means quotes could be auto-sent.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HOOK="${ROOT}/.claude/hooks/pre_send_quote.py"
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

echo "pre_send_quote.py - must BLOCK (exit 2):"
check "sendmail"        2 '{"tool_name":"Bash","tool_input":{"command":"sendmail -t < quote.txt"}}'
check "mailx"           2 '{"tool_name":"Bash","tool_input":{"command":"mailx -s Quote gc@example.com"}}'
check "mutt"            2 '{"tool_name":"Bash","tool_input":{"command":"mutt -a quotation.pdf -s Q gc@example.com"}}'
check "msmtp"           2 '{"tool_name":"Bash","tool_input":{"command":"msmtp gc@example.com < body.txt"}}'
check "postfix"         2 '{"tool_name":"Bash","tool_input":{"command":"postfix flush"}}'
check "curl to mail API" 2 '{"tool_name":"Bash","tool_input":{"command":"curl -X POST https://api.example.com/v3/mail/send"}}'
check "postmark API"    2 '{"tool_name":"Bash","tool_input":{"command":"curl -X POST https://api.postmarkapp.com/email"}}'
check "smtp"            2 '{"tool_name":"Bash","tool_input":{"command":"python -c \"import smtplib\""}}'
check "MCP send tool"   2 '{"tool_name":"mcp__gmail__send_email","tool_input":{}}'
check "MCP mail tool"   2 '{"tool_name":"mcp__outlook__mail_send","tool_input":{}}'

echo
echo "pre_send_quote.py - must ALLOW (exit 0):"
check "render the quote"      0 '{"tool_name":"Bash","tool_input":{"command":"python scripts/render_quote.py proj"}}'
check "write the email draft" 0 '{"tool_name":"Write","tool_input":{"file_path":"review/quotation_email_draft.md"}}'
check "read a price book"     0 '{"tool_name":"Read","tool_input":{"file_path":"pricebooks/index.json"}}'
check "list files"            0 '{"tool_name":"Bash","tool_input":{"command":"ls projects/"}}'

echo
if [[ "${FAIL}" -gt 0 ]]; then
  echo "GUARDRAIL FAILURE: ${FAIL} failed, ${PASS} passed. Do NOT run the pipeline unattended."
  exit 1
fi
echo "OK - ${PASS} checks passed. Sending is blocked (NFR-1)."
