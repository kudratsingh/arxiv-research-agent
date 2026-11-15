"""Reader coverage/export and exact-context links are frozen producer inputs."""
from pathlib import Path

import pytest

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import qualification_producer
from src.workspace.d5_freeze import code_bindings, verify

pytestmark = [pytest.mark.unit, pytest.mark.security]

READER_FILES = (
    "web/components/workspace/AssistanceTaskContext.tsx",
    "web/lib/workspace/api.ts",
    "web/lib/workspace/productContext.ts",
)


def test_coverage_export_and_exact_return_helpers_are_frozen():
    bindings = code_bindings()
    assert all(name in bindings for name in READER_FILES)
    assert all(bindings[name].startswith("sha256:") for name in READER_FILES)


@pytest.mark.parametrize("name", READER_FILES)
def test_changed_reader_helper_refuses_packet_before_dispatch(monkeypatch, name):
    original = Path.read_bytes
    root = Path(__file__).resolve().parents[1]
    target = root / name
    packet = {"approved": False, "code": code_bindings(),
              "adapter": qualification_producer(), "cases": []}
    packet["packet_digest"] = _digest(packet)

    def mutated(path):
        data = original(path)
        return data + b"\n// Synthetic drift control; no source file is modified.\n" if path == target else data

    monkeypatch.setattr(Path, "read_bytes", mutated)
    with pytest.raises(AdmissionError, match="d5_frozen_producer_changed"):
        verify(packet)
