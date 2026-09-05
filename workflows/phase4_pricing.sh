#!/usr/bin/env bash
# Phase 4 - Pricing - runs one phase independently. See workflows/README.md
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_phase.sh"
run_phase "${1:?Usage: phase4_pricing.sh <project_name>}" "pricing-engineer" "Phase 4 - Pricing" "Match every opening to the reference library first (product-matcher), then price each line via P21 last-PO, list x multiplier, or distributor/RFQ manual entry. Apply the product-type margin band as an editable default. Record cost source, detail, multiplier tier and effective date on every line. Write priced/line_items.json and priced/margin_applied.json."
