# syntax=docker/dockerfile:1.7

# ---------- Deps stage: install node_modules once, cached on lockfile.
FROM node:20-alpine AS deps
WORKDIR /app

# Copy manifest first so a source change doesn't invalidate the
# npm install layer.
COPY package.json package-lock.json* ./

RUN --mount=type=cache,target=/root/.npm \
    npm ci --ignore-scripts

# ---------- Build stage: produce `.next/standalone` for the runtime.
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Ship the API base to the client bundle at build time. Compose sets
# it via `--build-arg NEXT_PUBLIC_API_BASE=...` so a different host
# port doesn't require a rebuild of the whole tree.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

RUN npm run build

# ---------- Runtime stage: minimal footprint.
FROM node:20-alpine AS runtime
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

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs \
    && chown -R nextjs:nodejs /app
USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
