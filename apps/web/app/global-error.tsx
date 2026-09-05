"use client";

/**
 * Last resort: a failure in the root layout itself, where the app shell and its
 * stylesheet are not available. This file has to render its own <html> and can
 * rely on nothing above it, so the styling here is deliberately inline.
 */
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <html lang="en" data-theme="dark">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#0a0a12",
          color: "#e8e8f0",
          fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
        }}
      >
        <div style={{ maxWidth: 460, padding: 24, textAlign: "center" }}>
          <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Ops-Hub could not start</h1>
          <p style={{ fontSize: 13, lineHeight: 1.6, color: "#9a9ab0" }}>
            {error.message || "The application shell failed to load."}
          </p>
          <button
            onClick={retry}
            style={{
              marginTop: 12,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 600,
              color: "#fff",
              background: "#5b5bd6",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
          {error.digest && (
            <p style={{ fontSize: 11, color: "#6b6b80" }}>Reference {error.digest}</p>
          )}
        </div>
      </body>
    </html>
  );
}
