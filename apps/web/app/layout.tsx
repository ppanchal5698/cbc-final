import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ops-Hub — CBC Estimating",
  description:
    "The estimating and pricing desk for CBC — bid documents in, priced proposal out.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Theme is applied before paint so a reload does not flash the wrong palette. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{document.documentElement.dataset.theme=localStorage.getItem("opshub-theme")||"dark"}catch(e){}`,
          }}
        />
      </head>
      <body
        className={`${manrope.variable} font-sans antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            className: "bg-panel border-subtle text-tx-primary",
          }}
        />
      </body>
    </html>
  );
}
