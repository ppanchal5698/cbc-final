#!/usr/bin/env bash
# Phase 6 - Deliver - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase6_deliver.sh <project_name>}" "delivery-agent" "Phase 6 - Deliver" "Confirm the commercial terms are present, prepare the email body addressed to the specific sales initiator, list the open review flags in it, save review/quotation_email_draft.md via save_artifact, then HALT and report 'Draft ready for estimator review'. Do NOT send anything. Do NOT export the PDF or write uploads/final/ - the worker renders quotation.pdf with WeasyPrint after this pass and owns both."
