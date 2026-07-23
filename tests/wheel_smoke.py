"""Smoke test executed with a clean environment containing a built wheel."""

from __future__ import annotations

from importlib.metadata import version
import json
from pathlib import Path
import tempfile

import catseq
from catseq import _native
from catseq.targets import rtmq_v2_profile


assert catseq.__version__ == version("catseq")
assert callable(_native.compile)
assert callable(_native.execute_oasm_program)
assert _native.AssembledOASMProgram.__module__ == "catseq._native"
assert _native.LinuxRawEthernetRuntimeConfig.__module__ == "catseq._native"

runtime_board = _native.AssembledOASMBoard(
    "rwg0",
    [0x00D00000, 0x00D00000],
    1,
)
runtime_program = _native.AssembledOASMProgram(1, 20, 3, [runtime_board])
runtime_endpoint = _native.BoardEndpoint("rwg0", 2, 7, 1024)
runtime_config = _native.LinuxRawEthernetRuntimeConfig(
    1,
    "catseq-wheel-smoke-interface-that-does-not-exist",
    [2, 0, 0, 0, 0, 4],
    10,
    [runtime_endpoint],
)
runtime_failure = _native.execute_oasm_program(runtime_program, runtime_config)
assert isinstance(runtime_failure, _native.OASMRuntimeFailure)
assert runtime_failure.code == "transport_open_failed"
assert runtime_failure.board_evidence == {"rwg0": "not_dispatched"}

with tempfile.TemporaryDirectory(prefix="catseq-wheel-smoke-") as temporary:
    root = Path(temporary)
    source = root / "sequence.py"
    source.write_text(
        "from catseq.morphism import Morphism, identity\n\n"
        "def sequence() -> Morphism:\n"
        "    return identity(1)\n"
    )
    request = {
        "schema_version": 1,
        "source_path": str(source),
        "source_root": str(root),
        "entry": "sequence",
        "compile_environment": {"schema_version": 1, "channels": {}},
        "target_profile": rtmq_v2_profile(),
        "link_bindings": {
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {},
        },
        "cache_dir": str(root / "cache"),
    }
    response = json.loads(_native.compile(json.dumps(request).encode()))

assert response["stage"] == "oasm_call_plan"
assert response["logical_duration_cycles"] == 1
