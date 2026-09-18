"use client";

import Link from "next/link";
import { ArrowSquareOut } from "@phosphor-icons/react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { UploadPanel } from "@/components/intake/upload-panel";
import type { Project } from "@/lib/types";

/**
 * The plan set, straight off the board.
 *
 * The prototype's point is that there is no separate document store to open -
 * the bid documents live on the bid. This is the intake upload panel, rendered
 * where the estimator already is; it owns drag-and-drop, parse state and
 * delete, so none of that is written twice.
 */
export function PlansDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[760px]">
        {project ? (
          <>
            <DialogHeader>
              <DialogTitle>Plans on {project.code}</DialogTitle>
              <DialogDescription>
                {project.name}
                {project.gc ? ` · ${project.gc}` : ""} — uploaded straight onto this bid.
              </DialogDescription>
            </DialogHeader>

            <div className="max-h-[60vh] overflow-auto">
              {/* Empty initial list: the panel re-reads the documents itself. */}
              <UploadPanel code={project.code} initialDocuments={[]} />
            </div>

            <Link
              href={`/bids/${project.code}/intake`}
              className="flex items-center justify-center gap-2 rounded-lg border border-subtle bg-panel px-4 py-2.5 text-[13px] font-bold text-tx-secondary no-underline shadow-1 transition-colors hover:bg-panel-muted"
            >
              <ArrowSquareOut size={15} weight="bold" />
              Open in estimate
            </Link>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
