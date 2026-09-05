/**
 * Loading state for all four bid stages.
 *
 * Shaped like the real screen - header, stage bar, then the grid - so the
 * layout does not jump when the data lands.
 */
export default function BidStageLoading() {
  return (
    <>
      <div className="flex h-[54px] shrink-0 items-center gap-4 border-b border-subtle px-5 bg-background">
        <span className="skeleton h-3 w-52" />
        <span className="flex-1" />
        <span className="skeleton h-[34px] w-[200px] rounded-lg" />
        <span className="skeleton h-8 w-8 rounded-full" />
      </div>

      <div className="flex shrink-0 items-center gap-4 border-b border-subtle px-5 py-3 bg-background">
        <span className="flex w-[230px] shrink-0 flex-col gap-1.5">
          <span className="skeleton h-3 w-40" />
          <span className="skeleton h-2.5 w-28" />
        </span>
        <span className="flex flex-1 items-center gap-2.5">
          {Array.from({ length: 4 }).map((_, stage) => (
            <span key={stage} className="skeleton h-[50px] flex-1 rounded-lg" />
          ))}
        </span>
        <span className="hidden w-[150px] shrink-0 lg:block">
          <span className="skeleton block h-3 w-full" />
        </span>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden p-6" aria-busy="true" aria-live="polite">
        <span className="sr-only">Loading this bid…</span>
        <div className="overflow-hidden rounded-xl bg-panel border border-subtle shadow-sm">
          <div className="flex items-center gap-4 border-b border-subtle px-5 py-4">
            <span className="skeleton h-8 w-8 rounded-lg" />
            <span className="flex flex-col gap-1.5">
              <span className="skeleton h-3.5 w-28" />
              <span className="skeleton h-2.5 w-64" />
            </span>
          </div>
          {Array.from({ length: 9 }).map((_, row) => (
            <div
              key={row}
              className="flex items-center gap-4 border-b border-subtle px-5 py-3 last:border-b-0"
            >
              <span className="skeleton h-4 w-4 shrink-0" />
              <span className="skeleton h-6 w-6 shrink-0 rounded-md" />
              <span className="skeleton h-3 w-12 shrink-0" />
              <span className="skeleton h-3 flex-1" />
              <span className="skeleton h-3 w-20 shrink-0" />
              <span className="skeleton h-5 w-20 shrink-0 rounded-md" />
            </div>
          ))}
        </div>
      </main>
    </>
  );
}
