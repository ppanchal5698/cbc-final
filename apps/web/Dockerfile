# Next.js standalone build.
#
# `output: "standalone"` in next.config.ts emits a self-contained server, so the
# runtime stage carries neither the source nor the full node_modules tree.

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
COPY scripts ./scripts
# `npm ci` runs the postinstall hook, which copies the pdf.js worker react-pdf
# actually resolves. Skipping it ships a viewer that refuses to open a file.
RUN npm ci

FROM node:22-bookworm-slim AS builder
WORKDIR /app
# Anything the build renders is frozen into the image. This defaulted to unset,
# which dev-auth read as development, which baked the seed accounts and their
# passwords into .next/server/app/signin.html - a file no runtime environment
# variable can unwrite. The page is force-dynamic now; this is the second guard,
# so a build is safe even if that export is later removed.
ARG APP_ENV=production
ENV APP_ENV=$APP_ENV
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# public/ carries the pdf.js worker the postinstall step wrote into deps.
COPY --from=deps /app/public ./public
RUN npm run build

FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000
CMD ["node", "server.js"]
