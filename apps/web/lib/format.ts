/** Presentation helpers for currency and percentages in the UI. */

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatMoneyShort(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `$${Math.round(value).toLocaleString("en-US")}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Turn a FastAPI error body into text the toast can show. */
export function formatApiDetail(detail: unknown, fallback = "Something went wrong."): string {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        if (typeof entry === "string") return entry;
        if (entry && typeof entry === "object" && "msg" in entry) {
          return String((entry as { msg: unknown }).msg);
        }
        return null;
      })
      .filter(Boolean) as string[];
    return parts.length ? parts.join("; ") : fallback;
  }
  if (typeof detail === "object") {
    if ("message" in detail && typeof (detail as { message: unknown }).message === "string") {
      return (detail as { message: string }).message;
    }
    if ("msg" in detail && typeof (detail as { msg: unknown }).msg === "string") {
      return (detail as { msg: string }).msg;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return String(detail);
}
