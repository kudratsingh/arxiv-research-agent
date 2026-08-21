# syntax=docker/dockerfile:1.7

# ---------- Builder ----------------------------------------------------
# Installs deps into a virtualenv at /opt/venv so the runtime layer can
# copy a pre-built environment without carrying the build toolchain.
FROM python:3.14-slim AS builder

# ADR 0053: `HF_HOME` is one path, set identically in both stages. The
# embedding model is downloaded into it here and copied into the
# runtime image below; if the two values ever diverge, the runtime
# finds an empty cache and silently re-downloads ~90MB inside the first
# job's own timeout budget — the exact failure the bake removes.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache

# No OS build deps: every compiled dependency (PyMuPDF, faiss-cpu,
# psycopg-binary, torch) ships a cp314 wheel — pyproject's floors
# guarantee it (ADR 0045). If a future dep needs a source build,
# add build-essential + swig here rather than widening the runtime
# stage. (curl lives only in the runtime stage, for the HEALTHCHECK.)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copy only the dependency manifests first so the pip layer caches
# on unchanged deps. Source changes past this line don't invalidate
# the pip install layer.
COPY pyproject.toml README.md requirements-lock.txt ./

# ADR 0053: install the LOCK, not pyproject's ranges. `pip install .`
# re-resolved every range at build time, so the image ran a dependency
# set nobody had tested — CI installs `-r requirements-lock.txt`
# (ADR 0045) and the caps are only `< next major`, which leaves every
# untested minor of langgraph, anthropic and redis in scope for a
# container whose /healthz would report `ok` straight through such a
# break. Installing the lock first and the project `--no-deps` second
# means pip performs no resolution at all for the app's dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements-lock.txt

# ADR 0053: bake the embedding model into the image. Copied on its own,
# before `src`, so an edit anywhere else in the tree does not
# re-download ~90MB of weights on every build. The model id is read out
# of the module that owns it rather than repeated here — a second copy
# would drift, and drift means a runtime download again with nothing
# failing loudly.
COPY src/tools/embeddings.py /tmp/embeddings_source.py
RUN python - <<'PY'
import pathlib
import re

from sentence_transformers import SentenceTransformer

source = pathlib.Path("/tmp/embeddings_source.py").read_text()
match = re.search(r'^MODEL_NAME = "([^"]+)"', source, re.MULTILINE)
if match is None:
    raise SystemExit(
        "MODEL_NAME not found in src/tools/embeddings.py — the bake step "
        "must be updated with it, or the image ships without weights."
    )
# `device="cpu"` is a build-time detail only: it keeps the load off a
# builder's GPU if it has one. The runtime picks its own device from
# `settings.embedding_device`.
SentenceTransformer(match.group(1), device="cpu")
print(f"baked embedding model: {match.group(1)}")
PY

# Now bring in the source so `pip install .` picks up the actual
# package. `--no-deps` because we already installed the pinned
# transitive graph above.
COPY src ./src
RUN pip install --no-deps .

# ---------- Runtime ----------------------------------------------------
# Minimal image with the built venv + source + baked model weights,
# running as a non-root user. No build toolchain and no docs. It does
# carry the lockfile's test tooling (pytest, mypy, ruff): the lock is a
# whole-venv freeze, and ADR 0053 chose exact parity with the tested
# set over a smaller image. Splitting the lock into runtime and dev
# halves is the recorded follow-up.
FROM python:3.14-slim AS runtime

# `HF_HOME` must match the builder's value exactly — see the note there.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    HF_HOME=/opt/hf-cache

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

# ADR 0053: the pre-downloaded MiniLM weights. Owned by `app` because
# huggingface_hub writes lock files into its cache root even on a pure
# read, and a read-only cache would fall back to a network fetch.
COPY --from=builder --chown=app:app /opt/hf-cache /opt/hf-cache

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
# No `--log-config`: uvicorn parses that flag's value as an ini file,
# so `/dev/null` raised RuntimeError before the socket ever bound
# (ADR 0040). src.observability.logging configures the root logger.
CMD ["uvicorn", "src.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
