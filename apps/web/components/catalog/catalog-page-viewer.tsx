"use client";

import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { DownloadSimple, Minus, Plus, X } from "@phosphor-icons/react/dist/ssr";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = `/pdf.worker.min.mjs?v=${pdfjs.version}`;

const BASE_PAGE_WIDTH = 560;

/**
 * Bid-agnostic PDF viewer for a vendor price-book page hit.
 * Caller owns the blob URL lifetime (revoke on close).
 */
export function CatalogPageViewer({
  url,
  page,
  title,
  downloadName,
  onClose,
}: {
  url: string;
  page: number;
  title: string;
  downloadName?: string;
  onClose: () => void;
}) {
  const [pageNumber, setPageNumber] = useState(Math.max(1, page));
  const [pageCount, setPageCount] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [failure, setFailure] = useState<string | null>(null);

  // Follow the page the caller asked for, and forget the previous document's
  // failure along with it.
  const asked = `${url}#${page}`;
  const [showing, setShowing] = useState(asked);
  if (showing !== asked) {
    setShowing(asked);
    setPageNumber(Math.max(1, page));
    setFailure(null);
  }

  function download() {
    const link = document.createElement("a");
    link.href = url;
    link.download = downloadName ?? "price-book.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-background/80 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="flex items-center gap-3 border-b border-subtle bg-panel px-4 py-3 shadow-sm">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold text-tx-primary">{title}</h2>
          <p className="tnum text-[12px] font-medium text-tx-muted">
            Page {pageNumber}
            {pageCount ? ` of ${pageCount}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Zoom out"
            disabled={zoom <= 0.5}
            onClick={() => setZoom((z) => Math.max(0.5, Number((z - 0.15).toFixed(2))))}
            className="rounded-md p-2 border border-subtle text-tx-secondary hover:bg-panel-muted disabled:opacity-40"
          >
            <Minus size={14} weight="bold" />
          </button>
          <span className="tnum w-12 text-center text-[12px] font-medium text-tx-muted">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            aria-label="Zoom in"
            disabled={zoom >= 2.5}
            onClick={() => setZoom((z) => Math.min(2.5, Number((z + 0.15).toFixed(2))))}
            className="rounded-md p-2 border border-subtle text-tx-secondary hover:bg-panel-muted disabled:opacity-40"
          >
            <Plus size={14} weight="bold" />
          </button>
          <button
            type="button"
            onClick={() => setPageNumber((n) => Math.max(1, n - 1))}
            disabled={pageNumber <= 1}
            className="rounded-md px-2.5 py-1.5 text-[12.5px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted disabled:opacity-40"
          >
            Prev
          </button>
          <button
            type="button"
            onClick={() => setPageNumber((n) => (pageCount ? Math.min(pageCount, n + 1) : n + 1))}
            disabled={pageCount > 0 && pageNumber >= pageCount}
            className="rounded-md px-2.5 py-1.5 text-[12.5px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted disabled:opacity-40"
          >
            Next
          </button>
          <button
            type="button"
            onClick={download}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted"
          >
            <DownloadSimple size={14} weight="bold" />
            Download
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close viewer"
            className="rounded-md p-2 border border-subtle text-tx-secondary hover:bg-panel-muted"
          >
            <X size={16} weight="bold" />
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 justify-center overflow-auto bg-panel-muted p-6">
        {failure ? (
          <p className="self-center text-[13px] font-medium text-status-error">{failure}</p>
        ) : (
          <Document
            file={url}
            loading={
              <p className="self-center text-[13px] font-medium text-tx-muted">Loading sheet…</p>
            }
            onLoadSuccess={(pdf) => {
              setPageCount(pdf.numPages);
              setFailure(null);
            }}
            onLoadError={(err) => setFailure(err.message || "Could not open this PDF")}
          >
            <Page
              pageNumber={pageNumber}
              width={BASE_PAGE_WIDTH * zoom}
              renderTextLayer
              renderAnnotationLayer
            />
          </Document>
        )}
      </div>
    </div>
  );
}
