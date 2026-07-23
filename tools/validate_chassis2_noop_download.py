#!/usr/bin/env python3
"""Download the frozen two-board no-op to chassis 2 through Rust."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from catseq.compilation import (
    AssembledOASMBoard,
    AssembledOASMProgram,
    BoardEndpoint,
    CatSeqRuntimeError,
    LinuxRawEthernetRuntimeConfig,
    execute_oasm_program,
)


ROOT = Path(__file__).parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "oasm_parity"
    / "v1"
    / "runtime"
    / "two_board_noop_download.json"
)
INTERFACE = "eno1"
EXPECTED_SOURCE_MAC = bytes.fromhex("60cf84a7bbff")
EXPECTED_CHASSIS2_MAC = bytes.fromhex("60cf84a7bc01")
HOST_NODE = 20
CHANNEL = 0
BOARD_BINDINGS = (("rwg0", 2), ("rwg1", 5))
INSTRUCTION_CAPACITY_WORDS = 131_072
CAP_NET_RAW = 13
APPROVED_ICH_SHA256 = "c1d8db32da90e15240757339c479e21c6a1e225f16b119c549da55bf3a72692a"
APPROVED_LOADER_SHA256 = (
    "cd06d87a8ec249f9e8a87fc19d528dfdbd18be6cefba8bae4e4f2bd8b53b28b0"
)
APPROVED_WRITES = {
    2: "c53e308b1e54f3cbd3c54747a2be10201dfeb8cff3302e54fba0c6e967020fe2",
    5: "a59eaca59e7a7fd3c1b3e9b75669548e16fd7381d37844c05b97a47619329fb0",
}


def _format_mac(mac: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in mac)


def _effective_capabilities() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("CapEff:"):
            return int(line.split()[1], 16)
    raise RuntimeError("cannot read effective Linux capabilities")


def _read_interface_mac() -> bytes:
    path = Path("/sys/class/net") / INTERFACE / "address"
    try:
        return bytes.fromhex(path.read_text().strip().replace(":", ""))
    except FileNotFoundError as error:
        raise RuntimeError(f"refusing missing interface {INTERFACE!r}") from error


def _fresh_pinned_oasm_transcript() -> dict[str, object]:
    capture_path = ROOT / "tools" / "capture_oasm_runtime_transcript.py"
    spec = importlib.util.spec_from_file_location(
        "_catseq_chassis2_oasm_capture",
        capture_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the pinned-OASM capture tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.capture_transcript()


def _load_and_verify_fixture() -> tuple[dict[str, object], list[int]]:
    fixture = json.loads(FIXTURE.read_text())
    if _fresh_pinned_oasm_transcript() != fixture:
        raise RuntimeError("fixture differs from a fresh pinned-OASM transcript")
    expected_input = {
        "execution_mode": "download",
        "core": "rwg",
        "program": "nop(2)",
        "host_node": HOST_NODE,
        "channel": CHANNEL,
        "tag": 0,
        "destination_nodes": [node for _, node in BOARD_BINDINGS],
    }
    if fixture["schema_version"] != 1 or fixture["input"] != expected_input:
        raise RuntimeError("fixture is not the authorized chassis-2 no-op case")
    words = [int(word, 16) for word in fixture["ich_program"]["words"]]
    encoded_words = b"".join(word.to_bytes(4, "big") for word in words)
    if fixture["ich_program"]["sha256"] != APPROVED_ICH_SHA256:
        raise RuntimeError("fixture ICH digest is not the reviewed chassis-2 digest")
    if hashlib.sha256(encoded_words).hexdigest() != APPROVED_ICH_SHA256:
        raise RuntimeError("frozen ICH words do not match their recorded SHA-256")
    if fixture["loader_program"]["sha256"] != APPROVED_LOADER_SHA256:
        raise RuntimeError("fixture loader digest is not the reviewed chassis-2 digest")
    for write in fixture["rtlink"]["writes"]:
        node = write["node"]
        expected_digest = APPROVED_WRITES.get(node)
        if expected_digest is None or write["sha256"] != expected_digest:
            raise RuntimeError(f"node {node} has no reviewed RTLink write digest")
        encoded_frames = b"".join(
            bytes.fromhex(frame) for frame in write["frames"]
        )
        if hashlib.sha256(encoded_frames).hexdigest() != expected_digest:
            raise RuntimeError(f"node {node} RTLink frames differ from their digest")
    if fixture["ich_program"]["exception_handler_word"] != 20:
        raise RuntimeError("frozen exception handler is not the pinned OASM entry")
    return fixture, words


def _preflight() -> tuple[dict[str, object], list[int]]:
    fixture, words = _load_and_verify_fixture()
    source_mac = _read_interface_mac()
    if source_mac != EXPECTED_SOURCE_MAC:
        raise RuntimeError(
            f"refusing unknown {INTERFACE} source MAC {_format_mac(source_mac)}"
        )
    if EXPECTED_CHASSIS2_MAC != (
        int.from_bytes(source_mac, "big") + 2
    ).to_bytes(6, "big"):
        raise RuntimeError("chassis-2 destination is not source MAC + 2")
    if not (_effective_capabilities() & (1 << CAP_NET_RAW)):
        raise RuntimeError(
            "CAP_NET_RAW is not effective; run this explicit validation with "
            "an authorized capability or root"
        )
    return fixture, words


def main() -> None:
    fixture, words = _preflight()
    program = AssembledOASMProgram(
        1,
        HOST_NODE,
        CHANNEL,
        [
            AssembledOASMBoard(
                address,
                words,
                fixture["ich_program"]["exception_handler_word"],
            )
            for address, _ in BOARD_BINDINGS
        ],
    )
    config = LinuxRawEthernetRuntimeConfig(
        1,
        INTERFACE,
        list(EXPECTED_CHASSIS2_MAC),
        2_000,
        [
            BoardEndpoint(
                address,
                node,
                CHANNEL,
                INSTRUCTION_CAPACITY_WORDS,
            )
            for address, node in BOARD_BINDINGS
        ],
    )
    print(
        json.dumps(
            {
                "event": "hardware_preflight_passed",
                "runtime": "catseq Rust AF_PACKET",
                "interface": INTERFACE,
                "source_mac": _format_mac(EXPECTED_SOURCE_MAC),
                "destination_mac": _format_mac(EXPECTED_CHASSIS2_MAC),
                "reply_node": HOST_NODE,
                "reply_channel": CHANNEL,
                "boards": [
                    {"address": address, "node": node, "channel": CHANNEL}
                    for address, node in BOARD_BINDINGS
                ],
                "ich_sha256": fixture["ich_program"]["sha256"],
                "loader_sha256": fixture["loader_program"]["sha256"],
            }
        ),
        file=sys.stderr,
        flush=True,
    )

    try:
        success = execute_oasm_program(program, config)
    except CatSeqRuntimeError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": error.code,
                    "certainty": error.execution_certainty,
                    "board_evidence": error.board_evidence,
                    "device_exceptions": error.device_exceptions,
                    "message": str(error),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        raise

    expected_evidence = {address: "succeeded" for address, _ in BOARD_BINDINGS}
    if success.board_evidence != expected_evidence:
        raise RuntimeError(
            "incomplete chassis-2 result: "
            f"expected {expected_evidence!r}, got {success.board_evidence!r}"
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "case": fixture["case"],
                "runtime": "catseq Rust AF_PACKET",
                "board_evidence": success.board_evidence,
                "results": success.results,
                "device_exceptions": {},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
