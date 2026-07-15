"""Python facade for the native CatSeq source compiler."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
import importlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import hashlib
from typing import Any

from ..targets import rtmq_v2_profile
from .execution import oasm_call_plan_to_calls
from .types import OASMAddress, OASMCall


JsonObject = Mapping[str, Any]


class CatSeqCompileError(RuntimeError):
    """The native compiler rejected a source entry or its bindings."""


@dataclass(frozen=True, slots=True)
class OASMCompileResult:
    """One linked native compile result ready for the Python OASM adapter."""

    oasm_call_plan: JsonObject
    logical_duration_cycles: int
    clock_hz: int
    diagnostics: tuple[JsonObject, ...]
    incremental: JsonObject
    native_compile_seconds: float

    @property
    def total_duration_us(self) -> float:
        """Logical sequence duration in the unit expected by ``BaseExp``."""

        return self.logical_duration_cycles * 1_000_000 / self.clock_hz

    def to_oasm_calls(
        self,
        *,
        opaque_callables: Mapping[str, Callable[..., Any]] | None = None,
    ) -> dict[OASMAddress, list[OASMCall]]:
        """Decode this plan into calls accepted by the existing OASM assembler."""

        return oasm_call_plan_to_calls(
            self.oasm_call_plan,
            opaque_callables=opaque_callables,
        )


def compile_entry(
    entry: Callable[..., object],
    *arguments: object,
    environment: JsonObject | str | Path,
    source_root: str | Path | None = None,
    link_bindings: JsonObject | str | Path | None = None,
    compiler: str | Path | None = None,
) -> OASMCompileResult:
    """Compile one bound Morphism builder without executing its Python body.

    ``entry`` supplies source identity and host argument bindings only.  The
    source compiler parses the method and its reachable service/module graph;
    arbitrary attributes on the owning Python object never enter native IR.
    """

    function, owner = _bound_function(entry)
    source_path = _source_path(function)
    root = Path(source_root).resolve() if source_root else _source_root(function)
    try:
        source_path.resolve().relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"entry source {source_path} is outside source root {root}"
        ) from error

    runtime_values = _argument_bindings(function, owner, arguments)
    bindings = _merge_link_bindings(link_bindings, runtime_values)
    target = rtmq_v2_profile()
    target_clock_hz = _target_clock_hz(target)

    if compiler is None and not os.environ.get("CATSEQC_BIN"):
        response = _compile_in_process(
            source_path=source_path,
            source_root=root,
            entry=function.__qualname__,
            environment=environment,
            target=target,
            link_bindings=bindings,
        )
        return _decode_result(response, target_clock_hz)

    with tempfile.TemporaryDirectory(prefix="catseqc-") as temporary:
        temporary_path = Path(temporary)
        environment_path = _json_input(
            environment, temporary_path / "compile-environment.json"
        )
        target_path = _json_input(target, temporary_path / "target-profile.json")
        bindings_path = _json_input(
            bindings, temporary_path / "link-bindings.json"
        )
        command = [
            _compiler_path(compiler),
            "compile",
            str(source_path),
            "--source-root",
            str(root),
            "--entry",
            function.__qualname__,
            "--compile-environment",
            str(environment_path),
            "--target-profile",
            str(target_path),
            "--link-bindings",
            str(bindings_path),
            "--format",
            "json",
        ]
        command.extend(("--cache-dir", str(_cache_dir(root))))
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )

    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise CatSeqCompileError(message or "catseqc failed without a diagnostic")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise CatSeqCompileError("catseqc returned invalid JSON") from error
    return _decode_result(response, target_clock_hz)


def _compile_in_process(
    *,
    source_path: Path,
    source_root: Path,
    entry: str,
    environment: JsonObject | str | Path,
    target: JsonObject | str | Path,
    link_bindings: JsonObject | str | Path,
) -> object:
    try:
        _native = importlib.import_module("catseq._native")
        request = {
            "schema_version": 1,
            "source_path": str(source_path),
            "source_root": str(source_root),
            "entry": entry,
            "compile_environment": _json_payload(environment),
            "target_profile": _json_payload(target),
            "link_bindings": _json_payload(link_bindings),
            "cache_dir": str(_cache_dir(source_root)),
        }
        encoded = json.dumps(request, separators=(",", ":")).encode()
        response = _native.compile(encoded)
    except (
        ImportError,
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        raise CatSeqCompileError(str(error)) from error
    try:
        return json.loads(response)
    except (json.JSONDecodeError, TypeError) as error:
        raise CatSeqCompileError("native compiler returned invalid JSON") from error


def _bound_function(
    entry: Callable[..., object],
) -> tuple[Callable[..., object], object | None]:
    function = getattr(entry, "__func__", entry)
    owner = getattr(entry, "__self__", None)
    if not inspect.isfunction(function):
        raise TypeError("compile_entry requires a Python function or bound method")
    if "<locals>" in function.__qualname__:
        raise ValueError("compile_entry requires a module- or class-level definition")
    return function, owner


def _source_path(function: Callable[..., object]) -> Path:
    source = inspect.getsourcefile(function)
    if source is None:
        raise ValueError(f"cannot locate source for {function.__qualname__}")
    return Path(source).resolve()


def _source_root(function: Callable[..., object]) -> Path:
    source = _source_path(function)
    module = inspect.getmodule(function)
    if module is None or not module.__name__:
        return source.parent
    root = source.parent
    for _ in module.__name__.split(".")[:-1]:
        root = root.parent
    return root


def _argument_bindings(
    function: Callable[..., object],
    owner: object | None,
    arguments: tuple[object, ...],
) -> dict[str, object]:
    values: dict[str, object] = {}
    if owner is not None:
        _owner_bindings(owner, values)

    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    if owner is not None and parameters and parameters[0].name in {"self", "cls"}:
        parameters = parameters[1:]
    if len(arguments) > len(parameters):
        raise TypeError(
            f"{function.__qualname__} accepts {len(parameters)} compiler arguments, "
            f"got {len(arguments)}"
        )
    for parameter, argument in zip(parameters, arguments, strict=False):
        _value_bindings(parameter.name, argument, owner, values)
    return values


def _owner_bindings(owner: object, values: dict[str, object]) -> None:
    names: set[str] = set()
    if is_dataclass(owner):
        names.update(field.name for field in fields(owner))
    try:
        names.update(vars(owner))
    except TypeError:
        pass
    for cls in type(owner).__mro__:
        names.update(
            name
            for name, value in vars(cls).items()
            if not name.startswith("_") and not isinstance(value, property)
        )
    for name in names:
        try:
            value = getattr(owner, name)
        except (AttributeError, RuntimeError):
            continue
        encoded = _json_scalar_or_sequence(value)
        if encoded is not None:
            values[f"self.{name}"] = encoded


def _value_bindings(
    name: str,
    value: object,
    owner: object | None,
    values: dict[str, object],
) -> None:
    encoded = _json_scalar_or_sequence(value)
    if encoded is not None:
        values[name] = encoded
        return
    if not isinstance(value, Mapping):
        return
    for key, item in value.items():
        encoded_item = _json_scalar_or_sequence(item)
        if encoded_item is None:
            continue
        if isinstance(key, str):
            values[f'{name}["{key}"]'] = encoded_item
            continue
        key_name = getattr(key, "name", None)
        if isinstance(key_name, str):
            values[f"{name}.{key_name}"] = encoded_item
        if owner is None:
            continue
        for attribute in dir(type(owner)):
            if attribute.startswith("_"):
                continue
            try:
                declaration = getattr(type(owner), attribute)
            except (AttributeError, RuntimeError):
                continue
            if declaration is key:
                values[f"{name}[self.{attribute}]"] = encoded_item


def _json_scalar_or_sequence(value: object) -> object | None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        encoded = [_json_scalar_or_sequence(item) for item in value]
        if all(item is not None for item in encoded):
            return encoded
    return None


def _merge_link_bindings(
    source: JsonObject | str | Path | None,
    runtime_values: Mapping[str, object],
) -> JsonObject | str | Path:
    if isinstance(source, (str, Path)):
        if runtime_values:
            payload = json.loads(Path(source).read_text())
        else:
            return source
    else:
        payload = dict(source or {})
    if payload.get("schema_version", 1) != 1:
        raise ValueError("link bindings schema_version must be 1")
    merged_runtime = dict(payload.get("runtime_values", {}))
    for name, value in runtime_values.items():
        merged_runtime.setdefault(name, value)
    payload["schema_version"] = 1
    payload["runtime_values"] = merged_runtime
    payload.setdefault("environment_values", {})
    return payload


def _target_clock_hz(target: JsonObject | str | Path) -> int:
    payload = json.loads(Path(target).read_text()) if isinstance(target, (str, Path)) else target
    clock_hz = payload.get("clock_hz")
    if not isinstance(clock_hz, int) or isinstance(clock_hz, bool) or clock_hz <= 0:
        raise ValueError("target clock_hz must be a positive integer")
    return clock_hz


def _json_payload(source: JsonObject | str | Path) -> object:
    if isinstance(source, (str, Path)):
        return json.loads(Path(source).read_text())
    return source


def _json_input(source: JsonObject | str | Path, destination: Path) -> Path:
    if isinstance(source, (str, Path)):
        return Path(source)
    destination.write_text(json.dumps(source, separators=(",", ":")))
    return destination


def _compiler_path(compiler: str | Path | None) -> str:
    if compiler is not None:
        return str(compiler)
    configured = os.environ.get("CATSEQC_BIN")
    if configured:
        return configured
    executable = "catseqc.exe" if sys.platform == "win32" else "catseqc"
    installed = Path(sysconfig.get_path("scripts")) / executable
    if installed.is_file():
        return str(installed)
    discovered = shutil.which("catseqc")
    if discovered:
        return discovered
    raise CatSeqCompileError(
        "catseqc is not installed; install a CatSeq platform wheel"
    )


def _cache_dir(source_root: Path) -> Path:
    configured = os.environ.get("CATSEQ_CACHE_DIR")
    if configured:
        base = Path(configured)
    elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "catseq"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "catseq"
    source_key = hashlib.sha256(str(source_root).encode()).hexdigest()[:16]
    return base / "compiler" / source_key


def _decode_result(response: object, target_clock_hz: int) -> OASMCompileResult:
    if not isinstance(response, dict) or response.get("stage") != "oasm_call_plan":
        raise CatSeqCompileError("catseqc did not return an OASMCallPlan result")
    plan = response.get("oasm_call_plan")
    duration = response.get("logical_duration_cycles")
    clock_hz = response.get("clock_hz", target_clock_hz)
    if not isinstance(plan, dict):
        raise CatSeqCompileError("catseqc result has no OASMCallPlan")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        raise CatSeqCompileError("catseqc result has no logical duration")
    if not isinstance(clock_hz, int) or isinstance(clock_hz, bool) or clock_hz <= 0:
        raise CatSeqCompileError("catseqc result has an invalid target clock")
    diagnostics = response.get("diagnostics", ())
    incremental = response.get("incremental", {})
    if not isinstance(diagnostics, list) or not all(
        isinstance(item, dict) for item in diagnostics
    ):
        raise CatSeqCompileError("catseqc result has invalid diagnostics")
    if not isinstance(incremental, dict):
        raise CatSeqCompileError("catseqc result has invalid incremental statistics")
    return OASMCompileResult(
        oasm_call_plan=plan,
        logical_duration_cycles=duration,
        clock_hz=clock_hz,
        diagnostics=tuple(diagnostics),
        incremental=incremental,
        native_compile_seconds=float(response.get("native_compile_seconds", 0.0)),
    )
