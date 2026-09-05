import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendored, minified, and not ours to lint. pdf.worker.min.mjs alone
    // reported ~1,473 warnings, which buried every real finding in this repo.
    "public/**",
    "**/*.min.mjs",
    "e2e/**",
  ]),
]);

export default eslintConfig;
