"""Compare the in-process PyO3 transport with a standalone compiler process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

from catseq import _native


ROOT = Path(__file__).parents[1]
DEFAULT_COMPILER = ROOT / "rust" / "target" / "release" / "catseqc"


def _percentiles(samples: list[float]) -> tuple[float, float]:
    ordered = sorted(samples)
    p95_index = max(0, (len(ordered) * 95 + 99) // 100 - 1)
    return statistics.median(ordered), ordered[p95_index]


def _measure(action, samples: int) -> list[float]:
    durations = []
    for _ in range(samples):
        start = time.perf_counter()
        action()
        durations.append((time.perf_counter() - start) * 1_000)
    return durations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--compiler", type=Path, default=DEFAULT_COMPILER)
    arguments = parser.parse_args()
    if arguments.samples <= 0:
        parser.error("--samples must be positive")
    if not arguments.compiler.is_file():
        parser.error(f"compiler does not exist: {arguments.compiler}")

    with tempfile.TemporaryDirectory(prefix="catseq-transport-bench-") as temporary:
        root = Path(temporary)
        source = root / "sequence.py"
        source.write_text(
            "from catseq.morphism import Morphism, identity\n\n"
            "def sequence() -> Morphism:\n"
            "    return identity(1)\n"
        )
        environment = {"schema_version": 1, "channels": {}}
        target = {
            "schema_version": 1,
            "rtmq_abi_version": 2,
            "clock_hz": 250_000_000,
            "boards": {},
            "operations": {},
        }
        bindings = {
            "schema_version": 1,
            "runtime_values": {},
            "environment_values": {},
        }
        cache = root / "cache"
        request = json.dumps(
            {
                "schema_version": 1,
                "source_path": str(source),
                "source_root": str(root),
                "entry": "sequence",
                "compile_environment": environment,
                "target_profile": target,
                "link_bindings": bindings,
                "cache_dir": str(cache),
            },
            separators=(",", ":"),
        ).encode()
        environment_path = root / "environment.json"
        target_path = root / "target.json"
        bindings_path = root / "bindings.json"
        environment_path.write_text(json.dumps(environment))
        target_path.write_text(json.dumps(target))
        bindings_path.write_text(json.dumps(bindings))
        command = [
            str(arguments.compiler),
            "compile",
            str(source),
            "--source-root",
            str(root),
            "--entry",
            "sequence",
            "--compile-environment",
            str(environment_path),
            "--target-profile",
            str(target_path),
            "--link-bindings",
            str(bindings_path),
            "--cache-dir",
            str(cache),
            "--format",
            "json",
        ]

        def native_action():
            return _native.compile(request)

        def process_action():
            return subprocess.run(command, check=True, capture_output=True)

        native_action()
        process_action()
        native_samples = _measure(native_action, arguments.samples)
        process_samples = _measure(process_action, arguments.samples)

    native_median, native_p95 = _percentiles(native_samples)
    process_median, process_p95 = _percentiles(process_samples)
    print(f"samples={arguments.samples}")
    print(f"pyo3 median={native_median:.3f} ms p95={native_p95:.3f} ms")
    print(f"process median={process_median:.3f} ms p95={process_p95:.3f} ms")
    print(f"median speedup={process_median / native_median:.2f}x")


if __name__ == "__main__":
    main()
