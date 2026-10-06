"use client";

import { useRef } from "react";

/**
 * The proposal as the customer receives it: the server's own rendering - the one
 * template the PDF prints and the build job files - not a second copy drawn here.
 * A second copy is how the screen and the PDF came to disagree on their terms and
 * their grouping. `stamp` changes whenever the proposal does, and reloads it.
 */
export function ProposalDocument({ code, stamp }: { code: string; stamp: string }) {
  const frame = useRef<HTMLIFrameElement>(null);

  /** As tall as the document, so the page scrolls rather than the frame. */
  function fit() {
    const doc = frame.current?.contentDocument;
    if (frame.current && doc) frame.current.style.height = `${doc.documentElement.scrollHeight}px`;
  }

  return (
    <iframe
      key={stamp}
      ref={frame}
      title="Proposal"
      src={`/api/proxy/projects/${encodeURIComponent(code)}/proposal/render`}
      onLoad={fit}
      className="mx-auto block w-full max-w-[860px] rounded-xl border border-subtle/50 bg-white shadow-lg"
      style={{ minHeight: 640 }}
    />
  );
}
