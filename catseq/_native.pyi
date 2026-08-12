from pathlib import Path
from typing import Any, Callable


def compile(request: bytes, /) -> bytes: ...


def run_cli() -> int: ...


class CompiledSequence:
    @property
    def entry(self) -> str: ...
    @property
    def logical_duration_cycles(self) -> int: ...
    @property
    def clock_hz(self) -> int: ...
    @property
    def total_duration_us(self) -> float: ...
    @property
    def native_compile_seconds(self) -> float: ...
    @property
    def oasm_call_plan(self) -> dict[str, Any]: ...
    @property
    def diagnostics(self) -> list[str]: ...
    @property
    def incremental(self) -> dict[str, Any]: ...
    @property
    def _opaque_callables(self) -> dict[str, Callable[..., object]]: ...


class Compiler:
    def __init__(
        self,
        source_root: str | Path,
        compile_environment: bytes,
        target_profile: bytes,
        environment_values: bytes,
        opaque_callables: dict[str, Any],
        cache_dir: str | Path | None = None,
    ) -> None: ...
    def _collect_kernel_definitions(self, experiment: Any) -> Any: ...
    def _register_kernel_modules(self, experiment: Any) -> Any: ...

    @property
    def source_root(self) -> str: ...

    def compile(
        self,
        source_path: str | Path,
        entry: str,
        entry_opaque_callables: dict[str, Callable[..., object]],
        entry_arguments: bytes,
        link_bindings: bytes,
    ) -> CompiledSequence: ...


class EthernetRuntimeBackend:
    def __init__(
        self,
        interface: str,
        destination: str,
        reply: tuple[int, int],
        boards: dict[str, int],
        timeout_margin_ms: int = 10_000,
    ) -> None: ...

    @property
    def interface(self) -> str: ...
    @property
    def destination(self) -> str: ...
    @property
    def reply(self) -> tuple[int, int]: ...
    @property
    def boards(self) -> dict[str, int]: ...
    @property
    def timeout_margin_ms(self) -> int: ...

    def execute(
        self,
        program: AssembledOASMProgram,
        logical_duration_cycles: int,
        clock_hz: int,
        timeout_ms: int | None = None,
    ) -> OASMRuntimeSuccess | OASMRuntimeFailure: ...


class AssembledOASMBoard:
    def __init__(
        self,
        address: str,
        ich_words: list[int],
        exception_handler_word: int,
    ) -> None: ...

    @property
    def address(self) -> str: ...
    @property
    def ich_words(self) -> list[int]: ...
    @property
    def exception_handler_word(self) -> int: ...


class AssembledOASMProgram:
    def __init__(
        self,
        schema_version: int,
        reply_node: int,
        reply_channel: int,
        boards: list[AssembledOASMBoard],
    ) -> None: ...

    @property
    def schema_version(self) -> int: ...
    @property
    def reply_node(self) -> int: ...
    @property
    def reply_channel(self) -> int: ...
    @property
    def boards(self) -> list[AssembledOASMBoard]: ...


class BoardEndpoint:
    def __init__(
        self,
        address: str,
        node: int,
        channel: int,
        instruction_capacity_words: int,
    ) -> None: ...

    @property
    def address(self) -> str: ...
    @property
    def node(self) -> int: ...
    @property
    def channel(self) -> int: ...
    @property
    def instruction_capacity_words(self) -> int: ...


class LinuxRawEthernetRuntimeConfig:
    def __init__(
        self,
        schema_version: int,
        interface: str,
        destination_mac: list[int] | None,
        timeout_ms: int,
        boards: list[BoardEndpoint],
    ) -> None: ...

    @property
    def schema_version(self) -> int: ...
    @property
    def interface(self) -> str: ...
    @property
    def destination_mac(self) -> list[int] | None: ...
    @property
    def timeout_ms(self) -> int: ...
    @property
    def boards(self) -> list[BoardEndpoint]: ...


class OASMRuntimeSuccess:
    @property
    def schema_version(self) -> int: ...
    @property
    def board_evidence(self) -> dict[str, str]: ...
    @property
    def results(self) -> dict[str, list[int]]: ...


class OASMRuntimeFailure:
    @property
    def schema_version(self) -> int: ...
    @property
    def code(self) -> str: ...
    @property
    def message(self) -> str: ...
    @property
    def execution_certainty(self) -> str: ...
    @property
    def board_evidence(self) -> dict[str, str]: ...
    @property
    def device_exceptions(self) -> dict[str, tuple[int, int | None]]: ...
    @property
    def details(self) -> dict[str, str]: ...


def execute_oasm_program(
    program: AssembledOASMProgram,
    config: LinuxRawEthernetRuntimeConfig,
) -> OASMRuntimeSuccess | OASMRuntimeFailure: ...
