"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

/**
 * Shell-wide UI state.
 *
 * The notes drawer and the command palette open from several places - the
 * header, the action bar, a keyboard shortcut - so a small context beats
 * threading callbacks through four component layers.
 */
export type Theme = "dark" | "light";

interface UiState {
  notesOpen: boolean;
  openNotes: (ref?: string) => void;
  closeNotes: () => void;
  notesRef: string | null;

  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;

  /** The live Claude Code session for the bid on screen. */
  terminalOpen: boolean;
  setTerminalOpen: (open: boolean) => void;

  focusMode: boolean;
  toggleFocus: () => void;

  /** The palette, the header and the pre-paint script all used to own this. */
  theme: Theme;
  toggleTheme: () => void;

  /** Bumped whenever a note is logged, so counts refresh without a page reload. */
  notesVersion: number;
  bumpNotes: () => void;

  /** Signed-in role — drives admin-only technical error details. */
  userRole: string;
}

const Context = createContext<UiState | null>(null);

/**
 * Read a persisted preference without breaking hydration.
 *
 * The server has no localStorage, so getServerSnapshot returns the default.
 * useSyncExternalStore then applies the stored value on the client without a
 * setState-in-effect cascade. Both preferences are cosmetic; the theme itself
 * is already applied pre-paint by the inline script in app/layout.tsx.
 */
function stored(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null; /* private browsing */
  }
}

function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private browsing */
  }
}

const LS_EVENT = "opshub-local-preference";

function notifyPreferenceChange(): void {
  window.dispatchEvent(new Event(LS_EVENT));
}

function subscribePreferences(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(LS_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(LS_EVENT, onStoreChange);
  };
}

function getFocusSnapshot(): boolean {
  return stored("opshub-focus") === "1";
}

function getThemeSnapshot(): Theme {
  return stored("opshub-theme") === "light" ? "light" : "dark";
}

export function UiStateProvider({
  children,
  userRole = "estimator",
}: {
  children: React.ReactNode;
  userRole?: string;
}) {
  const [notesOpen, setNotesOpen] = useState(false);
  const [notesRef, setNotesRef] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [notesVersion, setNotesVersion] = useState(0);

  const focusMode = useSyncExternalStore(
    subscribePreferences,
    getFocusSnapshot,
    () => false,
  );
  const theme = useSyncExternalStore(
    subscribePreferences,
    getThemeSnapshot,
    () => "dark" as Theme,
  );

  const toggleTheme = useCallback(() => {
    const next: Theme = getThemeSnapshot() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    remember("opshub-theme", next);
    notifyPreferenceChange();
  }, []);

  const openNotes = useCallback((ref?: string) => {
    setNotesRef(ref ?? null);
    setNotesOpen(true);
  }, []);

  const toggleFocus = useCallback(() => {
    const next = !getFocusSnapshot();
    remember("opshub-focus", next ? "1" : "0");
    notifyPreferenceChange();
  }, []);

  // Ctrl/Cmd+K anywhere; C opens the call drawer unless you are typing.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }

      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);

      if (!typing && event.key.toLowerCase() === "c" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        setNotesOpen(true);
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo<UiState>(
    () => ({
      notesOpen,
      openNotes,
      closeNotes: () => setNotesOpen(false),
      notesRef,
      paletteOpen,
      setPaletteOpen,
      terminalOpen,
      setTerminalOpen,
      focusMode,
      toggleFocus,
      theme,
      toggleTheme,
      notesVersion,
      bumpNotes: () => setNotesVersion((v) => v + 1),
      userRole,
    }),
    [
      notesOpen,
      notesRef,
      openNotes,
      paletteOpen,
      terminalOpen,
      focusMode,
      toggleFocus,
      theme,
      toggleTheme,
      notesVersion,
      userRole,
    ],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useUiState(): UiState {
  const value = useContext(Context);
  if (!value) throw new Error("useUiState must be used inside UiStateProvider");
  return value;
}
