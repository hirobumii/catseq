"""Public compiler facade over the Rust-owned compiler session."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import inspect
import json
from pathlib import Path
import sys
from typing import Any

from . import _native
from ._native import CompiledSequence
from .compilation.native import (
    CatSeqCompileError,
    _bound_function,
    _cache_dir,
    _compile_bindings,
    _source_path,
)
from .targets import rtmq_v2_profile
from .types import Channel


class Compiler:
    """Compile restricted CatSeq source against one immutable system setup."""

    def __init__(
        self,
        *,
        source_root: str | Path,
        channels: Mapping[str, Channel],
        opaque_calls: Mapping[str, Callable[..., object]] | None = None,
        environment_values: Mapping[str, object] | None = None,
        target_profile: Mapping[str, Any] | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        root = Path(source_root).resolve()
        opaque_bindings, opaque_callables = _encode_opaque_calls(opaque_calls or {})
        environment = {
            "schema_version": 1,
            "channels": {
                source_name: _encode_channel(source_name, channel)
                for source_name, channel in channels.items()
            },
            "opaque_calls": opaque_bindings,
        }
        target = dict(
            rtmq_v2_profile() if target_profile is None else target_profile
        )
        cache = Path(cache_dir) if cache_dir is not None else _cache_dir(root)
        try:
            self._native = _native.Compiler(
                root,
                _encode_json(environment),
                _encode_json(target),
                _encode_json(dict(environment_values or {})),
                opaque_callables,
                cache,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise CatSeqCompileError(str(error)) from error

    @classmethod
    def from_system(cls, system: object) -> Compiler:
        """Create a compiler from a system's source and channel declarations."""

        try:
            source_root = getattr(system, "source_root")
            channels = getattr(system, "channels")
        except AttributeError as error:
            raise TypeError(
                "system must define source_root and channels"
            ) from error
        target_profile = getattr(system, "target_profile", None)
        if callable(target_profile):
            target_profile = target_profile()
        cache_dir = getattr(system, "cache_dir", None)
        opaque_calls = getattr(system, "opaque_calls", None)
        environment_values = getattr(system, "environment_values", None)
        return cls(
            source_root=source_root,
            channels=channels,
            opaque_calls=opaque_calls,
            environment_values=environment_values,
            target_profile=target_profile,
            cache_dir=cache_dir,
        )

    @property
    def source_root(self) -> Path:
        return Path(self._native.source_root)

    def compile(
        self,
        entry: Callable[..., object],
        *arguments: object,
    ) -> CompiledSequence:
        """Compile one source entry without executing its Python body."""

        function, owner = _bound_function(entry)
        source_path = _source_path(function)
        entry_arguments, runtime_values = _compile_bindings(
            function, owner, arguments
        )
        link_bindings = {
            "schema_version": 1,
            "runtime_values": runtime_values,
            "environment_values": {},
        }
        try:
            return self._native.compile(
                source_path,
                function.__qualname__,
                _source_opaque_callables(
                    function,
                    self.source_root,
                    source_path,
                ),
                _encode_json(entry_arguments),
                _encode_json(link_bindings),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise CatSeqCompileError(str(error)) from error


def _encode_channel(source_name: str, channel: Channel) -> dict[str, object]:
    if not isinstance(source_name, str) or not source_name:
        raise TypeError("channel source names must be non-empty strings")
    if not isinstance(channel, Channel):
        raise TypeError(f"channel {source_name!r} must be a catseq.Channel")
    return {
        "board": channel.board.id,
        "local_id": channel.local_id,
        "kind": channel.channel_type.name.lower(),
    }


def _encode_opaque_calls(
    opaque_calls: Mapping[str, Callable[..., object]],
) -> tuple[dict[str, object], dict[str, Callable[..., object]]]:
    bindings: dict[str, object] = {}
    callables: dict[str, Callable[..., object]] = {}
    for source_name, opaque_callable in opaque_calls.items():
        if not isinstance(source_name, str) or not source_name:
            raise TypeError("opaque call source names must be non-empty strings")
        if not callable(opaque_callable):
            raise TypeError(f"opaque call {source_name!r} must be callable")
        bindings[source_name] = {
            "callable": source_name,
            "args": [],
            "kwargs": {},
        }
        callables[source_name] = opaque_callable
    return bindings, callables


def _encode_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def _source_opaque_callables(
    entry: Callable[..., object],
    source_root: Path,
    entry_source_path: Path,
) -> dict[str, Callable[..., object]]:
    callables: dict[str, Callable[..., object]] = {}
    entry_module = _module_name_for_source(source_root, entry_source_path)

    def register(value: object) -> None:
        if not inspect.isfunction(value):
            return
        module = getattr(value, "__module__", None)
        qualified_name = getattr(value, "__qualname__", None)
        if (
            not isinstance(module, str)
            or not isinstance(qualified_name, str)
            or "<locals>" in qualified_name
        ):
            return
        callables[f"{module}.{qualified_name}"] = value
        try:
            same_source = _source_path(value) == entry_source_path
        except (OSError, TypeError, ValueError):
            same_source = False
        if same_source:
            callables[f"{entry_module}.{qualified_name}"] = value

    for value in entry.__globals__.values():
        register(value)

    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        module_name = getattr(module, "__name__", None)
        if not isinstance(module_file, str) or not isinstance(module_name, str):
            continue
        try:
            inside_source_root = Path(module_file).resolve().is_relative_to(
                source_root
            )
        except OSError:
            continue
        if not inside_source_root:
            continue
        for value in vars(module).values():
            if getattr(value, "__module__", None) == module_name:
                register(value)
    return callables


def _module_name_for_source(source_root: Path, source_path: Path) -> str:
    relative = source_path.relative_to(source_root)
    components = list(relative.parts)
    file_name = components.pop()
    if not file_name.endswith(".py"):
        raise ValueError(f"{source_path} is not a Python module")
    stem = file_name.removesuffix(".py")
    if stem != "__init__":
        components.append(stem)
    return ".".join(components)
