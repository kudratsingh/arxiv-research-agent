"""Hot-reloadable keystore (ADR 0037).

`settings.api_keys_file` points at a JSON `{name: secret}` file;
the app loads it at startup and a background `KeystoreReloader`
polls its mtime and swaps `app.state.api_keys` on change without
restarting the process. Tests cover the parse/format contract, the
initial-load path, and the reload-on-mtime-change path.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from src.api.auth import (
    ApiKeyPrincipal,
    KeystoreReloader,
    load_keystore_from_file,
)

pytestmark = pytest.mark.unit


def _write_keystore(path: Path, mapping: dict[str, str]) -> None:
    path.write_text(json.dumps(mapping), encoding="utf-8")


class TestLoadKeystoreFromFile:
    def test_parses_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "keys.json"
        _write_keystore(
            path, {"internal": "sk_a", "partner": "sk_b"}
        )
        got = load_keystore_from_file(path)
        assert got == {
            "sk_a": ApiKeyPrincipal(key_id="internal"),
            "sk_b": ApiKeyPrincipal(key_id="partner"),
        }

    def test_bad_json_raises_valueerror_with_path(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not-json", encoding="utf-8")
        with pytest.raises(ValueError, match=str(path)):
            load_keystore_from_file(path)

    def test_non_object_json_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text('["a", "b"]', encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            load_keystore_from_file(path)

    def test_empty_values_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        _write_keystore(path, {"name": ""})
        with pytest.raises(ValueError, match="empty"):
            load_keystore_from_file(path)

    def test_duplicate_secrets_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "dup.json"
        _write_keystore(path, {"alice": "sk_x", "bob": "sk_x"})
        with pytest.raises(ValueError, match="duplicate"):
            load_keystore_from_file(path)


class TestKeystoreReloader:
    @pytest.mark.asyncio
    async def test_initial_load_populates_and_seeds_mtime(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "keys.json"
        _write_keystore(path, {"a": "sk_1"})
        applied: list[dict] = []
        reloader = KeystoreReloader(
            path, applied.append, interval_sec=0.05
        )
        initial = await reloader.initial_load()
        assert initial == {"sk_1": ApiKeyPrincipal(key_id="a")}
        assert reloader._last_mtime is not None

    @pytest.mark.asyncio
    async def test_reload_picks_up_file_change(self, tmp_path: Path) -> None:
        """Write v1 → initial load → write v2 (with bumped mtime) →
        the reloader's next poll swaps in the new keystore."""
        path = tmp_path / "keys.json"
        _write_keystore(path, {"a": "sk_1"})
        applied: list[dict] = []
        reloader = KeystoreReloader(
            path, applied.append, interval_sec=0.02
        )
        await reloader.initial_load()

        run_task = asyncio.create_task(reloader.run())
        # Force the mtime forward — filesystem resolution is often
        # 1 second, and rewriting the same content within that
        # window won't register.
        _write_keystore(path, {"a": "sk_1", "b": "sk_2"})
        new_mtime = time.time() + 2.0
        os.utime(path, (new_mtime, new_mtime))

        # Wait for the poll to fire — the file change should show up
        # within a couple of intervals.
        for _ in range(20):
            await asyncio.sleep(0.05)
            if applied:
                break
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

        assert applied, "reloader never picked up the file change"
        new_keys = applied[-1]
        assert new_keys == {
            "sk_1": ApiKeyPrincipal(key_id="a"),
            "sk_2": ApiKeyPrincipal(key_id="b"),
        }

    @pytest.mark.asyncio
    async def test_bad_reload_retains_old_keystore(
        self, tmp_path: Path
    ) -> None:
        """A broken edit shouldn't lock legitimate callers out. The
        reloader logs the error, drops the change, and keeps the
        current in-memory keystore.

        We assert two invariants: (a) `_last_mtime` is NOT updated
        (so the next successful edit is still picked up), and
        (b) `apply` is never called.
        """
        path = tmp_path / "keys.json"
        _write_keystore(path, {"a": "sk_1"})
        applied: list[dict] = []
        reloader = KeystoreReloader(
            path, applied.append, interval_sec=0.02
        )
        await reloader.initial_load()
        good_mtime = reloader._last_mtime

        # Break the file + bump mtime so the reloader tries to reparse.
        path.write_text("{not-json", encoding="utf-8")
        bumped = time.time() + 2.0
        os.utime(path, (bumped, bumped))

        run_task = asyncio.create_task(reloader.run())
        await asyncio.sleep(0.15)
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

        assert applied == []
        assert reloader._last_mtime == good_mtime
