"""Assembly parity between the native 0.3 compiler and CatSeq 0.2.4."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from catseq.compilation import execute_oasm_calls, oasm_call_plan_to_calls


try:
    from oasm.dev.main import C_MAIN
    from oasm.dev.rsp import C_RSP
    from oasm.dev.rwg import C_RWG, amp_calib, nop
    from oasm.rtmq2 import assembler, disassembler

    OASM_AVAILABLE = True
except ImportError:
    OASM_AVAILABLE = False


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
RB1_ROOT = WORKSPACE_ROOT / "rb1-next"
FIXTURE_ROOT = REPOSITORY_ROOT / "rust/catseqc/tests/fixtures"
CATSEQC = REPOSITORY_ROOT / "rust/target/release/catseqc"

# Produced by CatSeq v0.2.4 with pulse_time=0.35 us, the pinned OASM ABI, and
# deterministic unit-valued calibration vectors.  These values deliberately
# come from the released compiler rather than a second implementation of the
# native scheduling algorithm.
V024_DISASSEMBLY_SHA256 = {
    "main": "f9614881fc1364bd05caf118456a3ffacc33076eb351db53975e592e286f4599",
    "rsp10": "7b65c7447a13d9a05790bc89725d5ffff0e83f2b1fb732e698450351b8d3e008",
    "rwg0": "9a6366dae13a26d7c5b5509d9a56fc96b9ae202e41fa4aabc50c6e3ac0e635dd",
    "rwg1": "decff57a5c96b9363261b2c2c54a852135756ace827997e74e77c441c7a37573",
    "rwg2": "cbbeaa82f5eb74ca944ea8581c25713af77f7abb151dd133bcb8d7dd8d07dac3",
    "rwg3": "c57f45e428a755e4f82213082f6a70482023016d864c441e69123591985214f9",
    "rwg4": "e45fe2fae06e8d66d32bc5adaae8b3e78ad39490c3a7aa2e5f50ef6e188f34b5",
    "rwg5": "f967fde18a3af6ed2f901375ddad7202406752243fdaa117ddb93644bf1cd4b0",
    "rwg8": "6dfb8597185c6c56e7b7fabb29e1fd2727e3a6d5887d27259752f2ca9762fc06",
    "rwg9": "a7cd3dcbcaee7c2fd756207b9874f74e33d5220654925dff92cc46af33250c4b",
}


def _apply_amp_calibration(_calibration: object) -> None:
    values = np.ones(32)
    amp_calib(0x00000000_00000000_00000000_FFFFFFFF, values)
    amp_calib(0x00000000_00000000_FFFFFFFF_00000000, values)
    nop(n=4)


def _native_plan() -> dict[str, object]:
    result = subprocess.run(
        [
            CATSEQC,
            "compile",
            RB1_ROOT / "experiments/computing/rydberg_transfer.py",
            "--source-root",
            RB1_ROOT,
            "--entry",
            "RydbergTransferExp.build_sequence",
            "--compile-environment",
            FIXTURE_ROOT / "rydberg_environment.json",
            "--target-profile",
            FIXTURE_ROOT / "rydberg_target.json",
            "--link-bindings",
            FIXTURE_ROOT / "rydberg_bindings.json",
            "--format",
            "json",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout)["oasm_call_plan"]


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
@pytest.mark.skipif(not CATSEQC.exists(), reason="release catseqc binary not built")
@pytest.mark.skipif(not RB1_ROOT.exists(), reason="rb1-next source checkout unavailable")
def test_native_rydberg_transfer_matches_v024_final_oasm_assembly() -> None:
    """The public compile-to-OASM boundary preserves the released result."""
    calls = oasm_call_plan_to_calls(
        _native_plan(),
        opaque_callables={
            "rb1system.modules.addressing.apply_amp_calibration": (
                _apply_amp_calibration
            ),
            "rb1system.modules.shuttling.apply_amp_calibration": (
                _apply_amp_calibration
            ),
        },
    )
    boards = [("main", C_MAIN), ("rsp10", C_RSP)] + [
        (f"rwg{index}", C_RWG) for index in (0, 1, 2, 3, 4, 5, 8, 9)
    ]
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        success, assembled = execute_oasm_calls(calls, assembler(None, boards))

    assert success, output.getvalue()
    assert assembled is not None
    cores = {"main": C_MAIN, "rsp10": C_RSP}
    actual = {}
    for address, _core in boards:
        lines = disassembler(core=cores.get(address, C_RWG))(assembled.asm[address])
        text = lines if isinstance(lines, str) else "\n".join(map(str, lines))
        actual[address] = hashlib.sha256(text.encode()).hexdigest()

    assert actual == V024_DISASSEMBLY_SHA256
