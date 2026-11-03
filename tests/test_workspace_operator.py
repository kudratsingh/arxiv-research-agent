"""Operator shell boundaries using synthetic bytes and a fake Docker executable.

No real container, database, credential or owner directory is touched. These
assert checksum/argument/failure behavior, not Postgres restore correctness;
real isolated backup/restore evidence is recorded separately by the operator.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = b"synthetic workspace archive\n"


@pytest.fixture
def operator(tmp_path: Path):
    binary = tmp_path / "fake bin"
    binary.mkdir()
    data = tmp_path / "private state with spaces"
    data.mkdir()
    (data / ".api-key").write_text("synthetic-operator-key")
    (data / ".api-key").chmod(0o600)
    log = tmp_path / "docker calls.jsonl"
    fake = binary / "docker"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        + textwrap.dedent(r"""
        import hashlib
        import json
        import os
        import sys
        from pathlib import Path

        args = sys.argv[1:]
        action = next((arg for arg in args if arg in {"pg_dump", "pg_restore", "createdb", "dropdb", "psql"}), "unsupported")
        content = sys.stdin.buffer.read() if action == "pg_restore" else b""
        with Path(os.environ["FAKE_DOCKER_LOG"]).open("a") as stream:
            stream.write(json.dumps({"args": args, "action": action, "input_sha256": hashlib.sha256(content).hexdigest()}) + "\n")
        if action == "pg_dump":
            if os.environ.get("FAKE_PG_DUMP_FAIL") == "1":
                sys.stdout.buffer.write(b"incomplete synthetic archive")
                sys.stderr.write("synthetic pg_dump failure\n")
                raise SystemExit(17)
            sys.stdout.buffer.write(b"synthetic workspace archive\n")
        elif action == "pg_restore":
            if os.environ.get("FAKE_PG_RESTORE_FAIL") == "1":
                raise SystemExit(23)
        elif action == "psql":
            sys.stdout.write("restored_works\n1\nrestored_notes\n1\n")
        elif action not in {"createdb", "dropdb"}:
            sys.stderr.write("unexpected synthetic Docker action\n")
            raise SystemExit(91)
    """)
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "WORKSPACE_DATA_DIR": str(data),
        "WORKSPACE_OWNER": "operator-test",
        "WORKSPACE_POSTGRES_URL": "postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace",
        "WORKSPACE_BACKUP_DB": "workspace",
        "VENV_PYTHON": sys.executable,
        "FAKE_DOCKER_LOG": str(log),
    }

    def invoke(*args, extra=None):
        return subprocess.run(
            ["bash", str(ROOT / "scripts/workspace-everyday.sh"), *args],
            cwd=ROOT,
            env={**env, **(extra or {})},
            capture_output=True,
            text=True,
            timeout=20,
        )

    def events():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def backup():
        result = invoke("backup")
        assert result.returncode == 0, result.stderr
        path = Path(
            next(
                line.removeprefix("Private backup: ")
                for line in result.stdout.splitlines()
                if line.startswith("Private backup: ")
            )
        )
        assert path.read_bytes() == ARCHIVE
        return path

    return SimpleNamespace(data=data, log=log, env=env, invoke=invoke, events=events, backup=backup)


def relocated_backup(operator, tmp_path: Path, *, legacy: bool = False) -> Path:
    original = operator.backup()
    moved_dir = tmp_path / "relocated backup directory"
    moved_dir.mkdir()
    moved = moved_dir / "renamed archive with spaces.dump"
    shutil.copy2(original, moved)
    sidecar = Path(str(moved) + ".sha256")
    if legacy:
        sidecar.write_text(hashlib.sha256(ARCHIVE).hexdigest() + "  " + str(original) + "\n")
    else:
        shutil.copy2(Path(str(original) + ".sha256"), sidecar)
    return moved


@pytest.mark.parametrize("legacy", [False, True])
def test_correct_relocated_backup_restores_exact_supplied_bytes_and_drops_only_disposable_database(
    operator, tmp_path: Path, legacy: bool
) -> None:
    moved = relocated_backup(operator, tmp_path, legacy=legacy)
    result = operator.invoke("restore-check", str(moved))
    assert result.returncode == 0, result.stderr
    assert "Exact supplied backup checksum verified." in result.stdout
    assert "original data was not replaced" in result.stdout
    events = operator.events()
    assert [event["action"] for event in events] == [
        "pg_dump",
        "createdb",
        "pg_restore",
        "psql",
        "dropdb",
    ]
    restore = next(event for event in events if event["action"] == "pg_restore")
    assert restore["input_sha256"] == hashlib.sha256(moved.read_bytes()).hexdigest()
    created = next(event["args"][-1] for event in events if event["action"] == "createdb")
    dropped = next(event["args"][-1] for event in events if event["action"] == "dropdb")
    assert (
        created == dropped
        and created.startswith("workspace_restore_check_")
        and created != "workspace"
    )
    for event in events:
        assert event["args"][:5] == [
            "compose",
            "-p",
            "arxiv-workspace-live",
            "-f",
            "compose.workspace.yml",
        ]


def test_new_sidecar_is_basename_relative_and_private(operator) -> None:
    path = operator.backup()
    sidecar = Path(str(path) + ".sha256")
    assert sidecar.read_text() == hashlib.sha256(ARCHIVE).hexdigest() + "  " + path.name + "\n"
    assert str(path.parent) not in sidecar.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert sidecar.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("legacy", [False, True])
def test_tampered_relocated_bytes_refuse_before_any_restore_docker_command(
    operator, tmp_path: Path, legacy: bool
) -> None:
    moved = relocated_backup(operator, tmp_path, legacy=legacy)
    before = operator.events()
    moved.write_bytes(b"tampered copied archive while original still exists")
    result = operator.invoke("restore-check", str(moved))
    assert result.returncode != 0
    assert "Backup checksum mismatch; nothing restored." in result.stderr
    assert operator.events() == before


@pytest.mark.parametrize(
    "contents",
    [
        "not a checksum",
        "f" * 63 + "  backup.dump",
        "g" * 64 + "  backup.dump",
        "f" * 64 + "\nextra entry",
    ],
)
def test_malformed_checksum_refuses_before_docker(operator, tmp_path: Path, contents: str) -> None:
    archive = tmp_path / "archive with spaces.dump"
    archive.write_bytes(ARCHIVE)
    Path(str(archive) + ".sha256").write_text(contents)
    result = operator.invoke("restore-check", str(archive))
    assert result.returncode != 0
    assert "Invalid backup checksum sidecar; nothing restored." in result.stderr
    assert operator.events() == []


def test_failed_dump_retains_private_incomplete_file_without_success_sidecar(operator) -> None:
    result = operator.invoke("backup", extra={"FAKE_PG_DUMP_FAIL": "1"})
    assert result.returncode != 0
    assert "Incomplete private file retained" in result.stderr
    assert "Private backup:" not in result.stdout
    files = list((operator.data / "backups").iterdir())
    assert len(files) == 1 and files[0].name.startswith(".workspace-")
    assert files[0].read_bytes() == b"incomplete synthetic archive"
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert [event["action"] for event in operator.events()] == ["pg_dump"]


def test_failed_restore_still_drops_only_new_disposable_database(operator, tmp_path: Path) -> None:
    moved = relocated_backup(operator, tmp_path)
    result = operator.invoke("restore-check", str(moved), extra={"FAKE_PG_RESTORE_FAIL": "1"})
    assert result.returncode != 0
    events = operator.events()
    assert [event["action"] for event in events] == ["pg_dump", "createdb", "pg_restore", "dropdb"]
    assert events[-1]["args"][-1] == events[1]["args"][-1]
    assert "Restore check passed" not in result.stdout
