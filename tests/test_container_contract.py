"""The Dockerfile's promises about the source tree (ADRs 0053/0054).

The build-time contract cannot be asserted only by running the app:
the image installs the generated runtime subset of the tested lock,
selects CPU-only Torch on amd64, and bakes MiniLM weights so the first
live job does not download them inside its own timeout budget.

Both fixes are only as good as their coupling to the source. The bake
step reads `MODEL_NAME` out of `src/tools/embeddings.py` with a regex,
and the two build stages have to agree on `HF_HOME` — a rename on
either side would silently restore the runtime download, with nothing
failing loudly. These are the cheap guards for that drift; they parse
the Dockerfile, they do not build it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
EMBEDDINGS_SRC = (ROOT / "src" / "tools" / "embeddings.py").read_text()

# The exact expression the Dockerfile's bake step runs. Kept as one
# constant so a change to either side has to come here too.
BAKE_PATTERN = r'^MODEL_NAME = "([^"]+)"'


def test_bake_regex_still_matches_the_model_constant() -> None:
    # If `MODEL_NAME` is renamed, reformatted onto two lines, or moved
    # to another module, the build step raises rather than shipping a
    # weightless image — but only if someone builds. This fails in CI
    # instead, on the commit that broke it.
    match = re.search(BAKE_PATTERN, EMBEDDINGS_SRC, re.MULTILINE)
    assert match is not None, (
        "src/tools/embeddings.py no longer exposes a module-level "
        "MODEL_NAME string literal; update the Dockerfile bake step."
    )
    assert match.group(1) == "sentence-transformers/all-MiniLM-L6-v2"


def test_dockerfile_reads_the_model_id_instead_of_repeating_it() -> None:
    # A second copy of the model id in the Dockerfile would drift from
    # the runtime's, and the drift's only symptom is a slow first job.
    assert BAKE_PATTERN in DOCKERFILE
    assert "COPY src/tools/embeddings.py" in DOCKERFILE
    assert "sentence-transformers/all-MiniLM-L6-v2" not in DOCKERFILE


def test_both_stages_agree_on_the_hf_cache_path() -> None:
    # The builder downloads into `HF_HOME` and the runtime reads from
    # it. Divergent values leave the runtime with an empty cache and a
    # network fetch on the first encode.
    homes = re.findall(r"HF_HOME=(\S+)", DOCKERFILE)
    assert len(homes) == 2, f"expected one HF_HOME per stage, got {homes}"
    assert homes[0] == homes[1]
    assert f"COPY --from=builder --chown=app:app {homes[0]} {homes[0]}" in (
        DOCKERFILE
    )


def test_no_volume_shadows_the_baked_cache() -> None:
    # A compose volume mounted at the cache path would hide the baked
    # weights behind an empty directory — the download would come back
    # and the image would just be bigger for nothing.
    compose = (ROOT / "docker-compose.yml").read_text()
    home = re.findall(r"HF_HOME=(\S+)", DOCKERFILE)[0]
    assert home not in compose


def test_dependencies_come_from_the_lockfile() -> None:
    # `pip install .` re-resolved pyproject's ranges at build time, so
    # the container ran a dependency set nobody had tested (ADR 0045
    # pins CI to the lock). The project itself is installed after, and
    # `--no-deps`, so pip performs no resolution for it either.
    assert (
        "COPY pyproject.toml README.md requirements-lock.txt "
        "requirements-runtime-lock.txt ./"
    ) in DOCKERFILE
    assert "pip install -r requirements-runtime-lock.txt" in DOCKERFILE
    assert "pip install --no-deps ." in DOCKERFILE
    assert re.search(r"pip install \.$", DOCKERFILE, re.MULTILINE) is None


def test_image_preinstalls_the_locked_cpu_only_torch_wheel() -> None:
    # PyPI's current Linux torch wheels resolve multi-gigabyte CUDA
    # dependencies on both amd64 and arm64. The official CPU index
    # carries the same locked public version with a +cpu local suffix.
    assert "TARGETARCH" not in DOCKERFILE
    assert "https://download.pytorch.org/whl/cpu" in DOCKERFILE
    assert "s/^torch==//p' requirements-runtime-lock.txt" in DOCKERFILE
    cpu_install = DOCKERFILE.index("https://download.pytorch.org/whl/cpu")
    runtime_install = DOCKERFILE.index(
        "pip install -r requirements-runtime-lock.txt"
    )
    assert cpu_install < runtime_install


def test_lock_is_installable_as_written() -> None:
    # A `pip freeze` of an editable dev venv emits `-e .` or an
    # absolute `file://` path for the project itself. Either one turns
    # the image build into a build of the host's checkout.
    lock = (ROOT / "requirements-lock.txt").read_text().splitlines()
    entries = [
        ln.strip()
        for ln in lock
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert entries, "lockfile has no pins"
    for entry in entries:
        assert "==" in entry, f"unpinned lock entry: {entry}"
        assert not entry.startswith("-e"), f"editable lock entry: {entry}"
        assert "file://" not in entry, f"local path in lock: {entry}"


def test_runtime_lock_is_an_exact_generated_subset() -> None:
    full_lines = {
        line.strip()
        for line in (ROOT / "requirements-lock.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    runtime_lines = {
        line.strip()
        for line in (ROOT / "requirements-runtime-lock.txt")
        .read_text()
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert runtime_lines
    assert runtime_lines < full_lines
    assert not {
        "pytest",
        "pytest-asyncio",
        "pytest-postgresql",
        "mypy",
        "ruff",
        "fakeredis",
    } & {line.split("==", 1)[0].lower() for line in runtime_lines}

    result = subprocess.run(
        [sys.executable, "scripts/derive_runtime_lock.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_bake_runs_after_the_dependency_install() -> None:
    # `SentenceTransformer` has to be importable for the bake, and the
    # bake has to sit before `COPY src` so an edit to any other module
    # doesn't re-download the weights on every build.
    install = DOCKERFILE.index("pip install -r requirements-runtime-lock.txt")
    bake = DOCKERFILE.index("COPY src/tools/embeddings.py")
    copy_src = DOCKERFILE.index("COPY src ./src")
    assert install < bake < copy_src
