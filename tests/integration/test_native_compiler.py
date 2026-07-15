from __future__ import annotations

import json
from pathlib import Path

from catseq.compilation import compile_entry
from catseq.morphism import Morphism, identity
from catseq.targets import rtmq_v2_profile


def _compile_entry_sequence() -> Morphism:
    return identity(1)


def test_pyo3_compiler_api_compiles_a_versioned_request(tmp_path) -> None:
    from catseq import _native

    source_path = tmp_path / "sequence.py"
    source_path.write_text(
        "from catseq.morphism import Morphism, identity\n\n"
        "def sequence() -> Morphism:\n"
        "    return identity(1)\n"
    )
    request = {
        "schema_version": 1,
        "source_path": str(source_path),
        "source_root": str(tmp_path),
        "entry": "sequence",
        "compile_environment": {"schema_version": 1, "channels": {}},
        "target_profile": rtmq_v2_profile(),
        "link_bindings": {
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {},
        },
        "cache_dir": str(tmp_path / "cache"),
    }

    response = json.loads(_native.compile(json.dumps(request).encode()))

    assert response["schema_version"] == 1
    assert response["stage"] == "oasm_call_plan"
    assert response["entry"] == "sequence"
    assert response["logical_duration_cycles"] == 1


def test_compile_entry_uses_the_real_pyo3_compiler(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CATSEQ_CACHE_DIR", str(tmp_path / "cache"))

    result = compile_entry(
        _compile_entry_sequence,
        environment={"schema_version": 1, "channels": {}},
        source_root=Path(__file__).parents[2],
    )

    assert result.logical_duration_cycles == 1
    assert result.clock_hz == 250_000_000
