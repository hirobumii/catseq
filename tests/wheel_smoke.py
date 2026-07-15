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
