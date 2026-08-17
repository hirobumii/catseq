from typing import Any


def _collect_kernel_definitions(experiment: Any, /) -> Any: ...


def _register_kernel_modules(experiment: Any, /) -> Any: ...


class _FrontendSession:
    def __init__(self, compile_environment: dict[str, Any], /) -> None: ...
    def _analyze_registered_kernel(
        self,
        experiment: Any,
        params: Any,
        /,
    ) -> _TypedSourceAnalysis: ...


class _TypedSourceAnalysis:
    @property
    def _entry_name(self) -> str: ...
    @property
    def _body_definitions(self) -> list[tuple[str, str]]: ...
    @property
    def _atomic_definitions(self) -> list[tuple[str, str, str, int, int]]: ...
    @property
    def _call_edges(self) -> list[tuple[str, str, str]]: ...
    @property
    def _external_reads(self) -> Any: ...
    @property
    def _morphism_compositions(self) -> list[tuple[str, str]]: ...
    @property
    def _duration_scales(
        self,
    ) -> list[tuple[str, str, str, str, str, int, int]]: ...
    @property
    def _compute_source_profile_id(self) -> str | None: ...
    @property
    def _compute_unit_count(self) -> int: ...
    @property
    def _compute_source_unit_count(self) -> int: ...
    @property
    def _compute_calls(
        self,
    ) -> list[tuple[int, int, str, str, str, int, int]]: ...
    @property
    def _compute_interfaces(
        self,
    ) -> list[tuple[int, list[str], str, str, str, str, int, int]]: ...


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
