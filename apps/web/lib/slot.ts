/**
 * Which component of an opening a quote line is.
 *
 * Nothing records this: `estimateLines` carry a description, not a slot. So it
 * is read off the description the way an estimator reads it, purely to order
 * and label the lines under an opening — a door and its frame first, then the
 * hardware in the order a set is written. It is never used to price, to match
 * or to decide anything.
 */
export const SLOT_ORDER = [
  "DOOR",
  "FRAME",
  "ANCHOR",
  "HINGES",
  "LOCKSET",
  "EXIT DEVICE",
  "CLOSER",
  "KICK PLATE",
  "THRESHOLD",
  "SWEEP",
  "ASTRAGAL",
  "DOOR MUTES",
  "HARDWARE",
] as const;

export type Slot = (typeof SLOT_ORDER)[number];

/**
 * Ordered most specific first: "door sweep" is a sweep, and a "frame anchor" is
 * an anchor, so the narrow terms have to win over DOOR and FRAME.
 */
const PATTERNS: [RegExp, Slot][] = [
  [/\bsweep\b/i, "SWEEP"],
  [/\bastragal\b/i, "ASTRAGAL"],
  [/\bthreshold\b/i, "THRESHOLD"],
  [/kick\s*plate|\bkickplate\b/i, "KICK PLATE"],
  [/silencer|door\s*mute/i, "DOOR MUTES"],
  [/\banchor\b/i, "ANCHOR"],
  [/\bhinge\b/i, "HINGES"],
  [/\bcloser\b/i, "CLOSER"],
  [/exit\s*device|panic|\bsvr\b|vertical\s*rod/i, "EXIT DEVICE"],
  [/\block\b|lockset|\blever\b|cylinder|deadbolt/i, "LOCKSET"],
  [/\bframe\b/i, "FRAME"],
  [/\bdoor\b/i, "DOOR"],
];

export function slotOf(description?: string | null): Slot {
  const text = description ?? "";
  for (const [pattern, slot] of PATTERNS) {
    if (pattern.test(text)) return slot;
  }
  return "HARDWARE";
}

/** Sort key, so a set reads in the order it is written on the sheet. */
export function slotRank(slot: Slot): number {
  const index = SLOT_ORDER.indexOf(slot);
  return index < 0 ? SLOT_ORDER.length : index;
}
