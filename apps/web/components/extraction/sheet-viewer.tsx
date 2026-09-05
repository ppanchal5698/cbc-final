"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { FilePdf, Minus, Plus, X, ArrowsOut } from "@phosphor-icons/react/dist/ssr";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import { documentUrl } from "@/lib/proxy-fetcher";
import type { BidDocument, LineItem } from "@/lib/types";

// The version query busts a cached worker from a previous pdfjs; a mismatched
// worker makes the viewer refuse to open any file.
pdfjs.GlobalWorkerOptions.workerSrc = `/pdf.worker.min.mjs?v=${pdfjs.version}`;

const BASE_PAGE_WIDTH = 520;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 10;
/** How much of the viewport the highlight should fill when auto-zooming. */
const FIT_RATIO = 0.88;

function zoomToFitHighlight(
  bbox: number[],
  pageSize: { width: number; height: number },
  viewportWidth: number,
  viewportHeight: number,
): number {
  const [x0, y0, x1, y1] = bbox;
  const bboxWidth = Math.max(x1 - x0, 1);
  const bboxHeight = Math.max(y1 - y0, 1);
  const scaleAtZoom1 = BASE_PAGE_WIDTH / pageSize.width;
  const widthAtZoom1 = bboxWidth * scaleAtZoom1;
  const heightAtZoom1 = bboxHeight * scaleAtZoom1;

  const zoomW = (viewportWidth * FIT_RATIO) / widthAtZoom1;
  const zoomH = (viewportHeight * FIT_RATIO) / heightAtZoom1;

  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.min(zoomW, zoomH)));
}

/**
 * The real drawing, with a highlight box over the spot a value was read from.
 *
 * This deliberately renders the source PDF rather than a re-rendering of the
 * extraction: checking Claude's output against Claude's output verifies nothing.
 * The box comes from `evidence.bbox`, in PDF points, scaled by the rendered
 * width over `evidence.pageSize.width`.
 */
export function SheetViewer({
  code,
  documents,
  selected,
  onClose,
}: {
  code: string;
  documents: BidDocument[];
  selected: LineItem | null;
  onClose: () => void;
}) {
  const [activeDocId, setActiveDocId] = useState(documents[0]?.id ?? "");
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [renderedWidth, setRenderedWidth] = useState(0);
  // Keyed by document: an unreadable PDF must not blank the viewer for the
  // others. Previously the failure branch replaced <Document> entirely, so the
  // onLoadSuccess that would have cleared it could never fire again.
  const [failures, setFailures] = useState<Record<string, string>>({});
  const frameRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);

  const evidence = selected?.evidence;
  const bbox = evidence?.bbox ?? null;
  const pageSize = evidence?.pageSize ?? null;

  const fitZoomToHighlight = useCallback(() => {
    if (!bbox || !pageSize || !frameRef.current) return;
    const pad = 24;
    const vw = Math.max(frameRef.current.clientWidth - pad, 1);
    const vh = Math.max(frameRef.current.clientHeight - pad, 1);
    setZoom(zoomToFitHighlight(bbox, pageSize, vw, vh));
  }, [bbox, pageSize]);

  // Follow the selected line to its page and document. Derived from which line
  // is selected rather than pushed from an effect, so the first render after a
  // selection already shows the right page.
  const [followed, setFollowed] = useState<string | null>(null);
  const selectionKey = selected ? `${selected.id}:${evidence?.sourcePage ?? ""}` : null;
  if (selectionKey && followed !== selectionKey) {
    setFollowed(selectionKey);
    if (evidence?.sourcePage) {
      setPageNumber(evidence.sourcePage);
      if (evidence.sourceFile) {
        const match = documents.find((doc) => evidence.sourceFile?.includes(doc.filename));
        if (match) setActiveDocId(match.id);
      }
    }
    if (!bbox || !pageSize) setZoom(1);
  }

  // Zoom in on the linked region whenever a line item with a bbox is selected.
  useEffect(() => {
    if (!bbox || !pageSize) return;
    // Wait for layout so viewport measurements reflect the open pane.
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => fitZoomToHighlight());
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [selected?.id, bbox, pageSize, fitZoomToHighlight]);

  // Bring the highlight into view once it exists.
  useEffect(() => {
    if (!highlightRef.current) return;
    highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  }, [bbox, renderedWidth, pageNumber, zoom]);

  const activeDoc = documents.find((doc) => doc.id === activeDocId) ?? documents[0];
  const failure = activeDoc ? failures[activeDoc.id] : undefined;

  const fileUrl = useMemo(
    () => (activeDoc ? documentUrl(code, activeDoc.id) : null),
    [code, activeDoc],
  );

  /**
   * The rendered canvas is the source of truth for scale.
   *
   * react-pdf's onRenderSuccess hands back a page proxy, not a width, so
   * measuring the canvas is both simpler and correct at any zoom.
   */
  const measurePage = useCallback(() => {
    const canvas = pageRef.current?.querySelector("canvas");
    if (canvas) setRenderedWidth(canvas.getBoundingClientRect().width);
  }, []);

  // Re-measure when the pane or zoom changes.
  useEffect(() => {
    const node = pageRef.current;
    if (!node) return;
    const observer = new ResizeObserver(measurePage);
    observer.observe(node);
    return () => observer.disconnect();
  }, [measurePage, activeDocId]);

  // The highlight only makes sense on the page the value was read from.
  const highlight = useMemo(() => {
    if (!bbox || !pageSize || !renderedWidth) return null;
    if (evidence?.sourcePage !== pageNumber) return null;

    const scale = renderedWidth / pageSize.width;
    const [x0, y0, x1, y1] = bbox;
    const padding = 3;

    return {
      left: x0 * scale - padding,
      top: y0 * scale - padding,
      width: (x1 - x0) * scale + padding * 2,
      height: (y1 - y0) * scale + padding * 2,
    };
  }, [bbox, pageSize, evidence?.sourcePage, renderedWidth, pageNumber]);

  if (!activeDoc || !fileUrl) {
    return (
      <aside className="flex w-full shrink-0 flex-col rounded-xl xl:w-[clamp(380px,34vw,560px)] bg-panel border border-subtle shadow-sm">
        <div className="grid flex-1 place-items-center px-8 py-16 text-center">
          <span className="text-[13.5px] font-medium text-tx-secondary">
            No bid documents uploaded yet.
          </span>
        </div>
      </aside>
    );
  }

  return (
    <aside className="anim-fadein flex h-[420px] w-full shrink-0 flex-col overflow-hidden rounded-xl xl:h-auto xl:w-[clamp(380px,34vw,560px)] bg-panel border border-subtle shadow-xl">
      <div className="flex items-center gap-3 border-b border-subtle bg-panel-muted/50 px-5 py-4">
        <FilePdf size={22} weight="duotone" className="text-cyan-500" />
        <span className="flex min-w-0 flex-1 flex-col leading-tight gap-0.5">
          <span className="truncate text-[14px] font-bold text-tx-primary tracking-tight">{activeDoc.filename}</span>
          <span className="text-[11.5px] font-medium text-tx-muted">
            page {pageNumber} of {pageCount || activeDoc.pages || "?"}
            {evidence?.sheet ? ` · ${evidence.sheet}` : ""}
          </span>
        </span>
        <button onClick={onClose} className="p-1.5 rounded-md text-tx-muted hover:text-tx-primary hover:bg-background transition-colors" aria-label="Hide the sheet">
          <X size={16} weight="bold" />
        </button>
      </div>

      <div className="flex items-center gap-2 border-b border-subtle bg-background px-4 py-2.5 shadow-inner">
        <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-thin">
          {documents.map((doc) => (
            <button
              key={doc.id}
              onClick={() => {
                setActiveDocId(doc.id);
                setPageNumber(1);
              }}
              aria-label={`Show ${doc.filename}`}
              aria-current={doc.id === activeDocId ? "page" : undefined}
              className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-bold transition-all shadow-sm ${
                doc.id === activeDocId
                  ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
                  : "bg-transparent text-tx-secondary hover:bg-panel hover:text-tx-primary"
              }`}
            >
              {doc.filename.replace(/\.pdf$/i, "").slice(0, 18)}
            </button>
          ))}
        </div>

        <span className="flex-1" />

        <div className="flex items-center gap-1.5 px-2">
          <button
            onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 0.2))}
            className="p-1.5 rounded-md text-tx-secondary hover:text-tx-primary hover:bg-panel transition-colors"
            aria-label="Zoom out"
          >
            <Minus size={16} weight="bold" />
          </button>
          <button
            onClick={() => setZoom(1)}
            className="tnum min-w-[48px] text-[12.5px] font-bold text-tx-secondary hover:text-tx-primary transition-colors text-center"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 0.2))}
            className="p-1.5 rounded-md text-tx-secondary hover:text-tx-primary hover:bg-panel transition-colors"
            aria-label="Zoom in"
          >
            <Plus size={16} weight="bold" />
          </button>
          <button
            onClick={fitZoomToHighlight}
            aria-label="Zoom to the highlight"
            className="p-1.5 rounded-md text-tx-secondary hover:text-tx-primary hover:bg-panel transition-colors ml-1 border-l border-subtle pl-2.5"
          >
            <ArrowsOut size={16} weight="bold" />
          </button>
        </div>
      </div>

      {evidence && !evidence.bbox && (
        <div className="px-5 py-3 text-[12px] font-medium bg-status-warning-soft text-status-warning border-b border-status-warning/30">
          This line has no recorded position on the sheet — showing page{" "}
          <strong className="font-bold">{evidence.sourcePage ?? "?"}</strong> without a highlight.
        </div>
      )}

      <div ref={frameRef} className="min-h-0 flex-1 overflow-auto p-4 bg-[#e8ecef] dark:bg-background custom-scrollbar">
        {failure ? (
          <div className="rounded-xl px-5 py-4 text-[13px] font-medium bg-status-error-soft border border-status-error/30 text-status-error shadow-sm max-w-md mx-auto mt-8">
            {failure}
            <button
              onClick={() =>
                setFailures((current) => {
                  const next = { ...current };
                  delete next[activeDoc.id];
                  return next;
                })
              }
              className="ml-3 font-bold underline underline-offset-4 hover:text-status-error/80 transition-colors"
            >
              Try again
            </button>
          </div>
        ) : (
          <Document
            file={fileUrl}
            key={activeDoc.id}
            onLoadSuccess={({ numPages }) => setPageCount(numPages)}
            onLoadError={(err) =>
              setFailures((current) => ({
                ...current,
                [activeDoc.id]: `Could not open ${activeDoc.filename}: ${err.message}`,
              }))
            }
            loading={
              <div className="grid place-items-center h-full p-8 text-center text-[13px] font-bold text-tx-muted animate-pulse">
                Opening the drawing…
              </div>
            }
          >
            <div ref={pageRef} className="relative inline-block shadow-2xl rounded-sm overflow-hidden">
              <Page
                pageNumber={pageNumber}
                width={BASE_PAGE_WIDTH * zoom}
                onRenderSuccess={measurePage}
                renderAnnotationLayer={false}
                renderTextLayer={false}
              />
              {highlight && (
                <div
                  ref={highlightRef}
                  className="pointer-events-none absolute rounded-[3px]"
                  style={{
                    left: highlight.left,
                    top: highlight.top,
                    width: highlight.width,
                    height: highlight.height,
                    background: "rgba(129,140,248,0.22)",
                    border: "3px solid var(--color-brand-primary)",
                    boxShadow: "0 0 0 9999px rgba(0,0,0,0.45)",
                  }}
                />
              )}
            </div>
          </Document>
        )}
      </div>

      {pageCount > 1 && (
        <div className="flex items-center gap-3 border-t border-subtle bg-panel px-5 py-3 shadow-[0_-4px_12px_rgba(0,0,0,0.05)]">
          <button
            onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
            disabled={pageNumber <= 1}
            className="rounded-lg px-3 py-1.5 text-[12px] font-bold disabled:opacity-40 border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
          >
            Previous
          </button>
          <span className="tnum flex-1 text-center text-[12.5px] font-bold tracking-widest uppercase text-tx-muted">
            {pageNumber} / {pageCount}
          </span>
          <button
            onClick={() => setPageNumber((p) => Math.min(pageCount, p + 1))}
            disabled={pageNumber >= pageCount}
            className="rounded-lg px-3 py-1.5 text-[12px] font-bold disabled:opacity-40 border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
          >
            Next
          </button>
        </div>
      )}
    </aside>
  );
}
