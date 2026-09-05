"use client";

import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal behaviour for the app's hand-rolled overlays.
 *
 * All four of them - the new-bid dialog, the command palette, the notes drawer
 * and the run terminal - are plain fixed-position divs. That renders correctly
 * but leaves keyboard users behind the overlay: Tab walks the page underneath,
 * and closing drops focus to the top of the document.
 *
 * This gives them the three things a dialog owes a keyboard: Escape closes it,
 * Tab cycles inside it, and focus returns to whatever opened it.
 *
 * Returns the ref to put on the overlay's container element.
 */
export function useDialog<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const ref = useRef<T | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    opener.current = document.activeElement as HTMLElement | null;
    const node = ref.current;

    // Focus whatever the overlay wants focused first, else the container.
    const first = node?.querySelector<HTMLElement>(FOCUSABLE);
    if (first) {
      first.focus();
    } else {
      node?.focus();
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !ref.current) return;

      const focusable = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null,
      );
      if (focusable.length === 0) return;

      const firstElement = focusable[0];
      const lastElement = focusable[focusable.length - 1];
      const active = document.activeElement;

      // Wrap at both ends, and pull focus back in if it has escaped the overlay.
      if (event.shiftKey && (active === firstElement || !ref.current.contains(active))) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && active === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Only take focus back if it is still somewhere in the closing overlay;
      // an action that navigated elsewhere should keep what it focused.
      const restore = opener.current;
      if (restore && document.body.contains(restore)) restore.focus();
    };
  }, [open, onClose]);

  return ref;
}
