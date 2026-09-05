"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * J/K to move, Enter to confirm, Space to select, Esc to clear.
 *
 * The extraction screen advertises these in its own subtitle, so they have to
 * work. Shortcuts stay inert while the caret is in a field, otherwise typing a
 * description would confirm rows.
 */
export function useRowKeys<T extends { id: string }>({
  rows,
  onConfirm,
  onToggleSelect,
  onOpen,
  enabled = true,
}: {
  rows: T[];
  onConfirm: (row: T) => void;
  onToggleSelect: (row: T) => void;
  onOpen?: (row: T) => void;
  enabled?: boolean;
}) {
  const [storedCursor, setCursor] = useState<number>(-1);

  // A shrinking list must not leave the cursor pointing past the end. Clamped
  // on the way out rather than corrected in an effect, so the render that sees
  // the shorter list already sees a valid cursor.
  const cursor = Math.min(storedCursor, rows.length - 1);

  const isTyping = useCallback(() => {
    const target = document.activeElement as HTMLElement | null;
    return (
      !!target &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable)
    );
  }, []);

  useEffect(() => {
    if (!enabled) return;

    function onKey(event: KeyboardEvent) {
      if (isTyping() || event.ctrlKey || event.metaKey || event.altKey) return;
      if (rows.length === 0) return;

      const key = event.key.toLowerCase();

      if (key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setCursor(Math.min(cursor + 1, rows.length - 1));
        return;
      }
      if (key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setCursor(Math.max(cursor - 1, 0));
        return;
      }

      const row = rows[cursor];
      if (!row) return;

      if (event.key === "Enter") {
        event.preventDefault();
        onConfirm(row);
      } else if (event.key === " ") {
        event.preventDefault();
        onToggleSelect(row);
      } else if (key === "o") {
        event.preventDefault();
        onOpen?.(row);
      } else if (event.key === "Escape") {
        setCursor(-1);
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, onConfirm, onToggleSelect, onOpen, enabled, isTyping]);

  // Keep the focused row on screen when moving with the keyboard.
  useEffect(() => {
    if (cursor < 0) return;
    const row = rows[cursor];
    if (!row) return;
    document
      .querySelector(`[data-row-id="${row.id}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [cursor, rows]);

  return {
    cursor,
    cursorId: cursor >= 0 ? (rows[cursor]?.id ?? null) : null,
    setCursor,
  };
}
