#!/usr/bin/env bash
# Phase 5 - Judgment and review - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase5_review.sh <project_name>}" "quality-reviewer" "Phase 5 - Judgment and review" "Score confidence on every match. Flag low-confidence items, missing fire ratings, unparsed content, manual and RFQ lines, and below-band margins. Search reference-library/prior_quotes/ for the closest prior quote. Suggest RFIs. Write review/review_flags.json and review/review_summary.html."
