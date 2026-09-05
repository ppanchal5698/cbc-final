import { Suspense } from "react";

import { SignInForm } from "@/components/auth/sign-in-form";
import { devAccounts } from "@/lib/dev-auth";

// The gate below is only as good as when it runs. This page was statically
// prerendered, so `devAccounts()` was evaluated at build time - and web/Dockerfile
// builds with no APP_ENV, which baked estimator@cbc.com / admin@cbc.com and their
// passwords into .next/server/app/signin.html. Setting APP_ENV on the runtime
// container could not remove them; the HTML was already written.
export const dynamic = "force-dynamic";

export default function SignInPage() {
  // Resolved on the server. Outside local development this is an empty list, so
  // the seed credentials never reach the browser at all.
  const quickAccounts = devAccounts();

  return (
    <div className="grid min-h-screen lg:h-screen lg:grid-cols-[1.15fr_0.85fr]">
      <div
        className="hidden flex-col justify-between border-r border-subtle p-10 lg:flex lg:p-[54px_60px_44px] bg-panel relative overflow-hidden"
      >
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_var(--tw-gradient-stops))] from-brand-primary/10 via-background to-background pointer-events-none"></div>
        <div className="flex items-baseline gap-3 relative">
          <span className="text-[19px] font-bold tracking-tight text-tx-primary">Hamilton Parker</span>
          <span className="text-[11.5px] font-bold uppercase tracking-[0.16em] text-tx-muted">
            Commercial Building Components
          </span>
        </div>

        <div className="max-w-[620px] relative">
          <div className="h-[5px] bg-tx-primary" />
          <div className="mt-1 h-px bg-tx-primary" />
          <h1 className="mt-[26px] text-[54px] font-bold leading-[0.98] tracking-tight xl:text-[74px] text-tx-primary">
            Ops&#8209;Hub
          </h1>
          <p className="mt-3.5 max-w-[520px] text-[18px] font-medium leading-[1.4] text-pretty xl:text-[22px] text-tx-secondary">
            The estimating and pricing desk for CBC — bid documents in, priced proposal out.
          </p>

          <div className="mt-[46px] grid max-w-[600px] grid-cols-3 gap-[26px]">
            {[
              ["7", "documents read per bid, schedules and elevations reconciled against addenda"],
              ["14", "price books and multiplier programs kept current by purchasing"],
              ["4", "steps from intake to the signed proposal, with every number traceable"],
            ].map(([figure, caption]) => (
              <span
                key={figure}
                className="text-[13px] font-medium leading-[1.55] text-tx-secondary"
              >
                <span className="tnum block text-[26px] font-bold text-tx-primary">
                  {figure}
                </span>
                {caption}
              </span>
            ))}
          </div>
        </div>

        <div className="text-[11.5px] font-medium text-tx-muted relative">
          Internal system · Estimating department · Columbus, Ohio
        </div>
      </div>

      <div className="flex flex-col justify-center px-8 py-10 lg:px-[60px] bg-background">
        {/* useSearchParams needs a boundary; the form is the only dynamic part. */}
        <Suspense fallback={null}>
          <SignInForm quickAccounts={quickAccounts} />
        </Suspense>
      </div>
    </div>
  );
}
