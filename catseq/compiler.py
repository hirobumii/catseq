"""Public compiler facade over the Rust-owned compiler session."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any

from . import _native
from ._native import CompiledSequence
from .compilation.native import (
    _argument_bindings,
    _bound_function,
    _cache_dir,
    _source_path,
    native_compile_errors,
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
        with native_compile_errors():
            self._native = _native.Compiler(
                root,
                _encode_json(environment),
                _encode_json(target),
                _encode_json(dict(environment_values or {})),
                opaque_callables,
                cache,
            )

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
        runtime_values = _argument_bindings(function, owner, arguments)
        link_bindings = {
            "schema_version": 1,
            "runtime_values": runtime_values,
            "environment_values": {},
        }
        with native_compile_errors():
            return self._native.compile(
                source_path,
                function.__qualname__,
                _encode_json(link_bindings),
            )


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
