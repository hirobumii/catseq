"""Smoke test executed with a clean environment containing a built wheel."""

from __future__ import annotations

from importlib.metadata import version
import json
from pathlib import Path
import tempfile

import catseq
from catseq import _native
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.base_module import BaseModule, BaseService
from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.device import DeviceList
from catseq.experiment.params import ExpParam, ExpParams, ScanPoint
from catseq.morphism import Morphism, identity
from catseq.targets import rtmq_v2_profile


SYNTHETIC_INTERFACE = "catseq-wheel-smoke-interface-that-does-not-exist"
SYNTHETIC_DESTINATION = "02:ca:75:ee:00:01"
SYNTHETIC_DESTINATION_BYTES = [2, 202, 117, 238, 0, 1]
SYNTHETIC_REPLY = (60_001, 31)
SYNTHETIC_BOARD_ROUTES = {"rwg0": 60_000}


def wheel_public_sequence() -> Morphism:
    return identity(1)


assert catseq.__version__ == version("catseq")
assert callable(_native.compile)
assert callable(_native.execute_oasm_program)
assert _native.Compiler.__module__ == "catseq._native"
assert _native.CompiledSequence.__module__ == "catseq._native"
assert _native.EthernetRuntimeBackend.__module__ == "catseq._native"
assert _native.AssembledOASMProgram.__module__ == "catseq._native"
assert _native.LinuxRawEthernetRuntimeConfig.__module__ == "catseq._native"
assert BaseExp.__module__ == "catseq.experiment.base_exp"
assert BaseModule.__module__ == "catseq.experiment.base_module"
assert BaseService.__module__ == "catseq.experiment.base_module"
assert DescartesGenerator.__module__ == "catseq.experiment.descartes"
assert DeviceList.__module__ == "catseq.experiment.device"
assert ExpParam.__module__ == "catseq.experiment.params"
assert ExpParams.__module__ == "catseq.experiment.params"
assert ScanPoint.__module__ == "catseq.experiment.params"

runtime_board = _native.AssembledOASMBoard(
    "rwg0",
    [0x00D00000, 0x00D00000],
    1,
)
runtime_program = _native.AssembledOASMProgram(1, *SYNTHETIC_REPLY, [runtime_board])
runtime_endpoint = _native.BoardEndpoint("rwg0", 60_000, 7, 1024)
runtime_config = _native.LinuxRawEthernetRuntimeConfig(
    1,
    SYNTHETIC_INTERFACE,
    SYNTHETIC_DESTINATION_BYTES,
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

    compiler = catseq.Compiler(
        source_root=Path(__file__).parent,
        channels={},
        cache_dir=root / "public-cache",
    )
    compiled = compiler.compile(wheel_public_sequence)
    runtime = catseq.EthernetRuntime(
        interface=SYNTHETIC_INTERFACE,
        destination=SYNTHETIC_DESTINATION,
        reply=SYNTHETIC_REPLY,
        boards=SYNTHETIC_BOARD_ROUTES,
    )

assert response["stage"] == "oasm_call_plan"
assert response["logical_duration_cycles"] == 1
assert isinstance(compiled, catseq.CompiledSequence)
assert compiled.logical_duration_cycles == 1
assert runtime.boards == SYNTHETIC_BOARD_ROUTES
