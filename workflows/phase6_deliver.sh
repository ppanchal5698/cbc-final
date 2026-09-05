#!/usr/bin/env bash
# Phase 6 - Deliver - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase6_deliver.sh <project_name>}" "delivery-agent" "Phase 6 - Deliver" "Export quotation.html to quotation.pdf with the standard commercial terms, prepare the email body addressed to the specific sales initiator, copy approved artifacts into uploads/final/, then HALT and report 'Draft ready for estimator review'. Do NOT send anything."
