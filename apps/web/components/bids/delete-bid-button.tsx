"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash } from "@phosphor-icons/react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { endpoints } from "@/lib/endpoints";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";

type DeleteBidButtonProps = {
  code: string;
  name: string;
  role: string;
};

export function DeleteBidButton({ code, name, role }: DeleteBidButtonProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirmCode, setConfirmCode] = useState("");
  const [busy, setBusy] = useState(false);

  if (role !== "admin") {
    return null;
  }

  function beginDelete() {
    if (
      !window.confirm(
        `Delete ${code} (${name})? This removes the bid and all uploaded files — PDFs, extractions, quotes, and run logs. This cannot be undone.`,
      )
    ) {
      return;
    }
    setConfirmCode("");
    setOpen(true);
  }

  async function confirmDelete() {
    if (confirmCode !== code) return;
    setBusy(true);
    try {
      await proxyMutate(endpoints.projectDelete(code), { method: "DELETE" });
      toast.success(`${code} deleted`, { description: "All bid files were removed." });
      setOpen(false);
      router.push("/bids");
      router.refresh();
    } catch (problem) {
      const message = errorMessage(problem);
      if (message.toLowerCase().includes("not permitted")) {
        toast.error("Only administrators can delete bids", { description: message });
      } else {
        toast.error("Could not delete that bid", { description: message });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="border-t border-subtle px-5 py-4 bg-background rounded-b-xl">
        <button
          type="button"
          onClick={beginDelete}
          className="flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-bold border border-status-error/30 text-status-error bg-status-error-soft hover:bg-status-error/10 transition-colors shadow-sm"
        >
          <Trash size={16} weight="fill" />
          Delete bid
        </button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={!busy}>
          <DialogHeader>
            <DialogTitle>Confirm delete</DialogTitle>
            <DialogDescription>
              Type <strong>{code}</strong> to permanently delete this bid and every file under{" "}
              <code>projects/</code>.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmCode}
            onChange={(event) => setConfirmCode(event.target.value)}
            placeholder={code}
            autoComplete="off"
            aria-label={`Type ${code} to confirm delete`}
            disabled={busy}
          />
          <DialogFooter>
            <button
              type="button"
              onClick={() => setOpen(false)}
              disabled={busy}
              className="rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmDelete}
              disabled={busy || confirmCode !== code}
              className="rounded-lg px-4 py-2 text-[13px] font-bold disabled:opacity-50 border border-status-error/30 text-status-error bg-status-error-soft hover:bg-status-error/10 transition-colors shadow-sm"
            >
              Delete permanently
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
