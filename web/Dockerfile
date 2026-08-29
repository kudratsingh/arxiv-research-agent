# syntax=docker/dockerfile:1.7

# ---------- Deps stage: install node_modules once, cached on lockfile.
FROM node:22-alpine AS deps
WORKDIR /app

# Copy manifest first so a source change doesn't invalidate the
# npm install layer.
COPY package.json package-lock.json* ./

RUN --mount=type=cache,target=/root/.npm \
    npm ci --ignore-scripts

# ---------- Build stage: produce `.next/standalone` for the runtime.
FROM node:22-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ---------- Runtime stage: minimal footprint.
FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# `output: 'standalone'` bundles a minimal server.js + trimmed
# node_modules subset into `.next/standalone`. Copy that plus the
# static assets and the public/ dir if it exists.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
# public/ is optional; conditional copy pattern via a placeholder.

# WO-30 / C5. `standalone` traces the SERVER's imports, and the healthcheck is
# not one of them — it is a separate `node` process the daemon spawns — so it
# has to be copied explicitly. It imports nothing but `node:http`, which is
# why one file is the whole of it.
COPY --from=builder /app/scripts/healthcheck.mjs ./scripts/healthcheck.mjs

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs \
    && chown -R nextjs:nodejs /app
USER nextjs

EXPOSE 3000

# WO-30 / 05-MIGRATION.md C5. This used to probe Next `/`, which proves only
# that the Node process is up: a container with a broken API_INTERNAL_BASE
# stayed "healthy" while every request 503'd (04-ARCHITECTURE.md §11 item 12).
# The probe now goes through the proxy to `/api/healthz`, so a 200 means the
# upstream was actually reached. It exits non-zero on anything but 200 and
# NEVER on `status: degraded` — restarting this container does not fix a dead
# Redis. See scripts/healthcheck.mjs for the whole argument.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD node scripts/healthcheck.mjs

CMD ["node", "server.js"]
