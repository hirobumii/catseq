"""Frozen-OASM runtime protocol transcript acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "oasm_parity"
    / "v1"
    / "runtime"
    / "two_board_noop_download.json"
)
CAPTURE = ROOT / "tools" / "capture_oasm_runtime_transcript.py"
REFRESH_GUIDANCE = (
    "intentional refresh: run `uv run python "
    "tools/capture_oasm_runtime_transcript.py --output /tmp/transcript.json`, "
    "review the synthetic-only diff, then update the fixture and digests together"
)


def _assert_digest(label: str, actual: str, expected: str) -> None:
    assert actual == expected, (
        f"{label} digest mismatch: expected={expected} actual={actual}; "
        f"{REFRESH_GUIDANCE}"
    )


def test_frozen_oasm_two_board_download_transcript_is_reproducible() -> None:
    completed = subprocess.run(
        [sys.executable, str(CAPTURE)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    recorded = json.loads(completed.stdout)
    expected = json.loads(FIXTURE.read_text())

    assert recorded["provenance"] == {
        "reference_pipeline": {
            "catseq_commit": "eab85d9cc3fb82072ccfe2abdd25f1cb2368d488",
            "catseq_nearest_release_tag": "v0.2.4",
            "catseq_reference_branch": "origin/release/0.2",
            "oasm_commit": "33b6c2538509e70475b49de5bd5a13ef334d4387",
            "oasm_package_version": "0.1.21.post1",
        },
        "capture": {
            "kind": "self_contained_oasm_runtime_protocol",
            "verified_components": ["oasm"],
            "catseq_source_executed": False,
            "routing": "synthetic_non_site",
        },
    }
    assert recorded["input"]["destination_nodes"] == [60_000, 60_002]
    assert recorded["input"]["host_node"] == 60_001
    assert recorded["input"]["channel"] == 0
    assert recorded["input"]["tag"] == 0

    ich = recorded["ich_program"]
    assert ich["word_count"] == 62
    assert ich["exception_handler_word"] == 20
    _assert_digest(
        "ICH",
        ich["sha256"],
        "da60b2e4711b34bba246d1778be73b420c3b46974f14072c01b7fbc6aa4d2d14",
    )
    assert len(ich["words"]) == 62

    loader = recorded["loader_program"]
    assert loader["word_count"] == 199
    _assert_digest(
        "loader",
        loader["sha256"],
        "42603ee7dc0c17265e7a469fc9eaedbdc6c5e325a310ad6482408443e7be655d",
    )
    assert loader["sections"] == {
        "loader_prologue": {"start": 0, "end": 6},
        "ich_download": {"start": 6, "end": 193},
        "launch": {"start": 193, "end": 199},
    }
    assert len(loader["words"]) == 199

    rtlink = recorded["rtlink"]
    assert rtlink["frame_size_bytes"] == 14
    assert rtlink["monitor_nodes"] == [60_000, 60_002]
    assert [write["node"] for write in rtlink["writes"]] == [60_000, 60_002]
    assert [write["frame_count"] for write in rtlink["writes"]] == [100, 100]
    for write, digest in zip(
        rtlink["writes"],
        (
            "191d96a0b18bb575981ba47c498852281e78d8d85dcc8357a5ee85e8b235f29f",
            "f7ba0a1bafcc0b9739a955f19fb52a77d7279296360d97cef02514f52a394d49",
        ),
        strict=True,
    ):
        _assert_digest(f"RTLink node {write['node']}", write["sha256"], digest)
    assert all(len(write["frames"]) == 100 for write in rtlink["writes"])
    assert recorded == expected, REFRESH_GUIDANCE
