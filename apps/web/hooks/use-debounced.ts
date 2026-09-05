"use client";

import { useEffect, useState } from "react";

/**
 * A value that settles after typing stops.
 *
 * The catalog and audit-log searches fired one request per keystroke; the part
 * composer and the command palette each hand-rolled their own setTimeout to
 * avoid it. One hook, so search behaves the same everywhere.
 */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return settled;
}
