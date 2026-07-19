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

    assert recorded == expected

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
        },
    }
    assert recorded["input"]["destination_nodes"] == [2, 5]
    assert recorded["input"]["host_node"] == 20
    assert recorded["input"]["channel"] == 0
    assert recorded["input"]["tag"] == 0

    ich = recorded["ich_program"]
    assert ich["word_count"] == 62
    assert len(ich["words"]) == 62

    loader = recorded["loader_program"]
    assert loader["word_count"] == 199
    assert loader["sha256"] == (
        "cd06d87a8ec249f9e8a87fc19d528dfdbd18be6cefba8bae4e4f2bd8b53b28b0"
    )
    assert loader["sections"] == {
        "loader_prologue": {"start": 0, "end": 6},
        "ich_download": {"start": 6, "end": 193},
        "launch": {"start": 193, "end": 199},
    }
    assert len(loader["words"]) == 199

    rtlink = recorded["rtlink"]
    assert rtlink["frame_size_bytes"] == 14
    assert rtlink["monitor_nodes"] == [2, 5]
    assert [write["node"] for write in rtlink["writes"]] == [2, 5]
    assert [write["frame_count"] for write in rtlink["writes"]] == [100, 100]
    assert [write["sha256"] for write in rtlink["writes"]] == [
        "c53e308b1e54f3cbd3c54747a2be10201dfeb8cff3302e54fba0c6e967020fe2",
        "a59eaca59e7a7fd3c1b3e9b75669548e16fd7381d37844c05b97a47619329fb0",
    ]
    assert all(len(write["frames"]) == 100 for write in rtlink["writes"])
