# syntax=docker/dockerfile:1.7

# ---------- Builder ----------------------------------------------------
# Installs deps into a virtualenv at /opt/venv so the runtime layer can
# copy a pre-built environment without carrying the build toolchain.
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# System deps needed to compile any wheels that don't have prebuilt
# aarch64/x86 binaries at our Python version. PyMuPDF and faiss-cpu
# both ship binary wheels for py314 as of writing; if that changes,
# add build-essential + swig here.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copy only the dependency manifest first so the pip layer caches
# on unchanged deps. Source changes past this line don't invalidate
# the pip install layer.
COPY pyproject.toml README.md ./

# Install runtime deps only — no editable install of the app yet, and
# no `[dev]` extras (tests + tooling are not shipped in the image).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install .

# Now bring in the source so `pip install .` picks up the actual
# package. `--no-deps` because we already installed the transitive
# graph above.
COPY src ./src
RUN pip install --no-deps .

# ---------- Runtime ----------------------------------------------------
# Minimal image with the built venv + source, running as a non-root
# user. No build toolchain, no test deps, no docs.
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000

# Runtime OS deps: curl for the HEALTHCHECK. Nothing else — the
# workflow uses pure Python for PDF parsing (PyMuPDF wheels bundle
# their C dependencies) and Anthropic HTTP client (uses stdlib).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash app

WORKDIR /app

# Copy the built venv + source. Use `--chown` so the non-root user
# owns everything without a follow-up chown pass.
COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /build /app

# Cache dirs the workflow writes to at runtime. Created as root
# then chowned so the non-root user can write to them; WORKDIR
# creates /app as root, so a plain `mkdir` after `USER app` would
# fail with EACCES on this parent. Persistent volumes in compose /
# a real deployment mount over these paths.
RUN mkdir -p /app/.cache /app/outputs \
    && chown -R app:app /app/.cache /app/outputs

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${API_PORT}/healthz" || exit 1

# Uvicorn direct with the factory. `--workers` is set to 1 by default;
# compose (or a real orchestrator) tunes this via the `command`
# override once the RedisJobStore lands so multi-worker doesn't
# require sticky sessions for polling.
CMD ["uvicorn", "src.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--log-config", "/dev/null"]
