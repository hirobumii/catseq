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
    assert recorded["input"]["host_node"] == 21
    assert recorded["input"]["channel"] == 0
    assert recorded["input"]["tag"] == 0

    ich = recorded["ich_program"]
    assert ich["word_count"] == 62
    assert ich["exception_handler_word"] == 20
    assert ich["sha256"] == (
        "01a6507ace878c2684b066c640d21d1ae116fab83e679b0a94a4bb1735338994"
    )
    assert len(ich["words"]) == 62

    loader = recorded["loader_program"]
    assert loader["word_count"] == 199
    assert loader["sha256"] == (
        "466bcedeccc47c0922d7242af8186ac7958844e6274ad69393ef72344cacd9f9"
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
        "6a9a8b971df191966a6108346af61c22c5af192fab50eacaba4ac850807ea090",
        "ec25ba503d40ac7bae99f65dc5777d041b73599e6bcad0d698ca589dee5755ae",
    ]
    assert all(len(write["frames"]) == 100 for write in rtlink["writes"])
