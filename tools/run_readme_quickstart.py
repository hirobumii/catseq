#!/usr/bin/env python3
"""Extract, execute, and validate the marked README quickstart."""

from __future__ import annotations

from pathlib import Path
import os
import runpy
import tempfile


ROOT = Path(__file__).parents[1]
README = ROOT / "README.md"
START = "<!-- catseq-release-check: quickstart:start -->"
END = "<!-- catseq-release-check: quickstart:end -->"
EXPECTED_CYCLES = 125_000_000


def extract_quickstart(readme: str) -> str:
    try:
        marked = readme.split(START, 1)[1].split(END, 1)[0].strip()
    except IndexError as error:
        raise RuntimeError("README quickstart markers are missing or malformed") from error
    lines = marked.splitlines()
    if len(lines) < 3 or lines[0] != "```python" or lines[-1] != "```":
        raise RuntimeError("marked README quickstart must contain one Python fence")
    return "\n".join(lines[1:-1]) + "\n"


def validate_quickstart(namespace: dict[str, object]) -> None:
    compiled = namespace.get("compiled")
    if compiled is None:
        raise RuntimeError("README quickstart did not publish a compiled value")
    duration = getattr(compiled, "logical_duration_cycles", None)
    if duration != EXPECTED_CYCLES:
        raise RuntimeError(
            f"README quickstart duration mismatch: expected={EXPECTED_CYCLES} "
            f"actual={duration}"
        )
    plan = getattr(compiled, "oasm_call_plan", None)
    try:
        calls = plan["epochs"][0]["boards"][0]["calls"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("README quickstart produced an invalid OASM Call Plan") from error
    if not calls or calls[0]["function"] != "ttl_config":
        raise RuntimeError("README quickstart must configure TTL before its first drive")
    ttl_sets = [call for call in calls if call["function"] == "ttl_set"]
    if not ttl_sets or ttl_sets[0]["args"][:2] != [1, 1]:
        raise RuntimeError("README quickstart does not drive TTL channel 0 high")
    if ttl_sets[-1]["args"][:2] != [1, 0]:
        raise RuntimeError("README quickstart does not return TTL channel 0 low")


def main() -> None:
    source = extract_quickstart(README.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="catseq-readme-quickstart-") as directory:
        path = Path(directory) / "quickstart_ttl.py"
        path.write_text(source, encoding="utf-8")
        previous_cache = os.environ.get("CATSEQ_CACHE_DIR")
        os.environ["CATSEQ_CACHE_DIR"] = str(Path(directory) / "cache")
        try:
            namespace = runpy.run_path(str(path))
        finally:
            if previous_cache is None:
                os.environ.pop("CATSEQ_CACHE_DIR", None)
            else:
                os.environ["CATSEQ_CACHE_DIR"] = previous_cache
    validate_quickstart(namespace)
    print(f"README quickstart PASS: {EXPECTED_CYCLES} cycles, initialized TTL")


if __name__ == "__main__":
    main()
