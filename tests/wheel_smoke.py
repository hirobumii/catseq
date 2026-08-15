"""Smoke test executed with a clean environment containing a built wheel."""

from __future__ import annotations

from importlib.util import find_spec
from importlib.metadata import version

import catseq
from catseq import _native
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.base_module import BaseModule, BaseService
from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.device import DeviceList
from catseq.experiment.params import ExpParam, ExpParams, ScanPoint
from catseq.oasm import black_box


SYNTHETIC_INTERFACE = "catseq-wheel-smoke-interface-that-does-not-exist"
SYNTHETIC_DESTINATION_BYTES = [2, 202, 117, 238, 0, 1]
SYNTHETIC_REPLY = (60_001, 31)


assert catseq.__version__ == version("catseq")
assert callable(_native._collect_kernel_definitions)
assert callable(_native._register_kernel_modules)
assert callable(_native.execute_oasm_program)
assert black_box.__module__ == "catseq.oasm"
assert find_spec("catseq.atomic") is None
assert find_spec("catseq.compiler") is None
assert not hasattr(catseq, "Compiler")
assert not hasattr(catseq, "CompiledSequence")
assert not hasattr(catseq, "EthernetRuntime")
assert not hasattr(_native, "compile")
assert not hasattr(_native, "Compiler")
assert not hasattr(_native, "CompiledSequence")
assert not hasattr(_native, "run_cli")
assert _native._FrontendSession.__module__ == "catseq._native"
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
