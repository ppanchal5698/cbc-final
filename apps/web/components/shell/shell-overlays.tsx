"use client";

import { usePathname } from "next/navigation";

import { CommandPalette } from "@/components/shell/command-palette";
import { NotesDrawer } from "@/components/shell/notes-drawer";
import { TerminalDrawer } from "@/components/terminal/terminal-drawer";

/**
 * The drawer and the palette, mounted once for the whole app.
 *
 * Both need the bid currently on screen, which the path already carries -
 * /bids/{code}/... - so there is nothing to thread down from the server.
 */
export function ShellOverlays() {
  const pathname = usePathname();
  const match = pathname.match(/^\/bids\/([^/]+)/);
  const code = match ? decodeURIComponent(match[1]) : null;

  return (
    <>
      <NotesDrawer code={code} />
      <CommandPalette code={code} />
      <TerminalDrawer code={code} />
    </>
  );
}
