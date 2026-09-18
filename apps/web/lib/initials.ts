/** Display helpers for people and brand names in the shell / board. */

/** Initials for avatars — never throws on null/empty session fields. */
export function userInitials(
  name?: string | null,
  initials?: string | null,
): string {
  const provided = initials?.trim();
  if (provided) return provided.slice(0, 3).toUpperCase();

  const derived = String(name ?? "E")
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return derived || "E";
}

/** Brand chip initials on the bid board — null brand → Unbranded. */
export function brandInitials(brand?: string | null): string {
  return userInitials(brand?.trim() || "Unbranded");
}
