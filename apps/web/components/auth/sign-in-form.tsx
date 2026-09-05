"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";

import { safeRedirectPath } from "@/lib/safe-redirect";

/** Passed in from the server page, which decides whether to offer them at all. */
export interface QuickAccount {
  label: string;
  name: string;
  email: string;
  password: string;
}

export function SignInForm({ quickAccounts = [] }: { quickAccounts?: QuickAccount[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Where the session expired, so signing back in returns to the same screen.
  const from = searchParams.get("from");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitCredentials(nextEmail: string, nextPassword: string) {
    setBusy(true);
    setError(null);

    const result = await signIn("credentials", {
      email: nextEmail,
      password: nextPassword,
      redirect: false,
    }).catch(() => null);

    if (!result || result.error) {
      setError(
        result
          ? "That email and password do not match an account."
          : "Could not reach the sign-in service. Try again in a moment.",
      );
      setBusy(false);
      return;
    }

    router.push(safeRedirectPath(from));
    router.refresh();
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    await submitCredentials(email, password);
  }

  async function onQuickSignIn(account: QuickAccount) {
    setEmail(account.email);
    setPassword(account.password);
    await submitCredentials(account.email, account.password);
  }

  return (
    <form onSubmit={onSubmit} className="mx-auto w-full max-w-[400px] p-8 rounded-2xl bg-panel border border-subtle shadow-xl shadow-black/5 relative overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-primary via-brand-primary/50 to-brand-primary"></div>
      
      <div className="mb-8 text-center">
        <h2 className="text-[24px] font-bold tracking-tight text-tx-primary">Welcome back</h2>
        <p className="mt-2 text-[14px] font-medium text-tx-secondary">
          Sign in to your Hamilton Parker account
        </p>
      </div>

      <div className="space-y-5">
        <div>
          <label
            htmlFor="signin-email"
            className="block text-[12px] font-bold uppercase tracking-widest text-tx-muted mb-2"
          >
            Email
          </label>
          <input
        id="signin-email"
        type="email"
        required
        autoComplete="username"
        aria-invalid={!!error}
        aria-describedby={error ? "signin-error" : undefined}
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        className="w-full rounded-xl px-4 py-3 text-[14px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-2 focus:ring-brand-border focus:border-brand-primary transition-all shadow-sm"
        placeholder="name@hamiltonparker.com"
      />
      </div>

      <div>
        <label
          htmlFor="signin-password"
          className="block text-[12px] font-bold uppercase tracking-widest text-tx-muted mb-2"
        >
          Password
        </label>
        <input
          id="signin-password"
          type="password"
          required
          autoComplete="current-password"
          aria-invalid={!!error}
          aria-describedby={error ? "signin-error" : undefined}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded-xl px-4 py-3 text-[14px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-2 focus:ring-brand-border focus:border-brand-primary transition-all shadow-sm"
          placeholder="••••••••"
        />
      </div>
      </div>

      {error && (
        <p
          id="signin-error"
          role="alert"
          className="animate-in fade-in slide-in-from-top-1 mt-6 rounded-xl px-4 py-3 text-[13px] font-medium bg-status-error-soft border border-status-error/30 text-status-error shadow-sm"
        >
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="mt-8 w-full rounded-xl py-3.5 text-[14px] font-bold tracking-wide transition-all shadow-md active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100 bg-brand-primary text-white hover:bg-brand-primary/90 hover:shadow-brand-primary/20 hover:shadow-lg"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>

      {quickAccounts.length > 0 && (
        <div className="mt-8 pt-8 border-t border-subtle">
          <p className="text-[12px] font-bold uppercase tracking-widest text-tx-muted mb-4 text-center">
            Developer shortcuts
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {quickAccounts.map((account) => (
              <button
                key={account.email}
                type="button"
                disabled={busy}
                onClick={() => onQuickSignIn(account)}
                className="group flex flex-col items-start rounded-xl p-3 text-left transition-all border border-subtle bg-background hover:bg-panel-muted hover:border-brand-border disabled:opacity-50"
              >
                <span className="block text-[13.5px] font-bold text-tx-primary group-hover:text-brand-primary transition-colors">{account.label}</span>
                <span className="mt-1 block text-[12px] font-medium text-tx-secondary truncate w-full">
                  {account.email}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </form>
  );
}
