/**
 * Vendor RFQ (FR-16) and RFI (Phase 5) vocabularies, mirrored from the API's
 * quoting/domain/rfqs_and_rfis.py - collections.mongodb.md §3.28 and §3.29.
 */

export const RFQ_TRIGGERS = {
  customSize: "Custom size",
  unusualPrep: "Unusual prep",
  notSoldInYears: "Not sold in years",
  nonStock: "Non-stock item",
  firstTime: "First time buying it",
  beyondCutoff: "Beyond the manual cut-off",
} as const;

export type RfqTrigger = keyof typeof RFQ_TRIGGERS;

export type RfqStatus =
  | "draft"
  | "requested"
  | "awaiting"
  | "received"
  | "applied"
  | "expired"
  | "cancelled";

/** The edges the API accepts. Anything else it refuses with a 400. */
const RFQ_TRANSITIONS: Record<RfqStatus, readonly RfqStatus[]> = {
  draft: ["requested", "cancelled"],
  requested: ["awaiting", "cancelled"],
  awaiting: ["received", "expired", "cancelled"],
  received: ["applied", "expired", "cancelled"],
  applied: [],
  expired: [],
  cancelled: [],
};

/** Where an RFQ may go next. A new RFQ is a draft; an unknown state goes nowhere. */
export function nextRfqStatuses(current: string | null | undefined): readonly RfqStatus[] {
  return RFQ_TRANSITIONS[(current ?? "draft") as RfqStatus] ?? [];
}

export const RFI_CATEGORIES = {
  missingRating: "Missing fire rating",
  missingHanding: "Missing handing",
  missingFinish: "Missing finish",
  scopeAmbiguity: "Scope ambiguity",
  substitutionApproval: "Substitution approval",
  quantityAmbiguity: "Quantity ambiguity",
  other: "Other",
} as const;

export type RfiCategory = keyof typeof RFI_CATEGORIES;

export type RfiStatus = "open" | "sent" | "answered" | "closed" | "withdrawn";

/** The RFI edges the API accepts; `answered` also needs the answer itself. */
const RFI_TRANSITIONS: Record<RfiStatus, readonly RfiStatus[]> = {
  open: ["sent", "withdrawn"],
  sent: ["answered", "withdrawn"],
  answered: ["closed"],
  closed: [],
  withdrawn: [],
};

/** Where an RFI may go next. A new RFI is open; an unknown state goes nowhere. */
export function nextRfiStatuses(current: string | null | undefined): readonly RfiStatus[] {
  return RFI_TRANSITIONS[(current ?? "open") as RfiStatus] ?? [];
}
