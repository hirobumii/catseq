#!/usr/bin/env python3
"""Validate the frozen two-board no-op Download case on RTMQ chassis 2."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from oasm.dev.rwg import C_RWG
import oasm.rtmq2 as rtmq2
from oasm.rtmq2.intf import eth_intf

from capture_oasm_runtime_transcript import capture_transcript


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
DESTINATION_NODES = [2, 5]


def _format_mac(mac: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in mac)


class _ValidatedChassis2Interface(eth_intf):
    def __init__(self, expected_buffers: list[bytes]) -> None:
        super().__init__(INTERFACE)
        self.expected_buffers = expected_buffers
        self.validated_writes = 0
        self.completed: set[tuple[int, int]] = set()
        self.exceptions: list[dict[str, Any]] = []

    def _dev_wr(self, frame: bytes) -> None:
        index = self.validated_writes
        if index >= len(self.expected_buffers):
            raise RuntimeError("refusing an unexpected additional RTLink write")
        expected = self.expected_buffers[index]
        if bytes(frame) != expected:
            raise RuntimeError(
                f"refusing RTLink write {index}: bytes differ from the frozen fixture"
            )
        self.validated_writes += 1
        super()._dev_wr(frame)

    def _proc_oper(self, chn: int, payload: list[int]) -> tuple[int, bool]:
        address, finished = super()._proc_oper(chn, payload)
        if finished:
            self.completed.add((chn, address))
        return address, finished

    def _proc_info(self, payload: list[int]) -> tuple[int, int, bool]:
        channel, address, is_exception = super()._proc_info(payload)
        if is_exception:
            self.exceptions.append(
                {
                    "channel": channel,
                    "node": address,
                    "flag": payload[1],
                }
            )
        return channel, address, is_exception


def _load_and_verify_fixture() -> tuple[dict[str, Any], list[bytes]]:
    fixture = json.loads(FIXTURE.read_text())
    freshly_recorded = capture_transcript()
    if freshly_recorded != fixture:
        raise RuntimeError("frozen fixture differs from a fresh pinned-OASM capture")

    expected_input = {
        "execution_mode": "download",
        "core": "rwg",
        "program": "nop(2)",
        "host_node": HOST_NODE,
        "channel": CHANNEL,
        "tag": 0,
        "destination_nodes": DESTINATION_NODES,
    }
    if fixture["input"] != expected_input:
        raise RuntimeError("fixture is not the authorized chassis-2 no-op case")

    expected_buffers = [
        b"".join(bytes.fromhex(frame) for frame in write["frames"])
        for write in fixture["rtlink"]["writes"]
    ]
    return fixture, expected_buffers


def main() -> None:
    fixture, expected_buffers = _load_and_verify_fixture()
    interface = _ValidatedChassis2Interface(expected_buffers)

    if interface.src != EXPECTED_SOURCE_MAC:
        raise RuntimeError(
            f"refusing unknown {INTERFACE} source MAC {_format_mac(interface.src)}"
        )
    if interface.dst != EXPECTED_CHASSIS2_MAC:
        raise RuntimeError(
            f"refusing non-chassis-2 destination MAC {_format_mac(interface.dst)}"
        )
    derived_destination = (int.from_bytes(interface.src, "big") + 2).to_bytes(
        6, "big"
    )
    if interface.dst != derived_destination:
        raise RuntimeError("chassis-2 destination is not source MAC + 2")

    interface.nod_adr = HOST_NODE
    interface.loc_chn = CHANNEL
    interface.dev_tot = 0.1
    runner = rtmq2.run_cfg(
        interface,
        DESTINATION_NODES,
        mon=DESTINATION_NODES,
        chn=CHANNEL,
        tag=0,
        core=C_RWG,
    )

    def noop_program() -> None:
        rtmq2.nop(2)

    print(
        json.dumps(
            {
                "event": "hardware_preflight_passed",
                "interface": INTERFACE,
                "source_mac": _format_mac(interface.src),
                "destination_mac": _format_mac(interface.dst),
                "host_node": HOST_NODE,
                "destination_nodes": DESTINATION_NODES,
                "loader_sha256": fixture["loader_program"]["sha256"],
            }
        ),
        file=sys.stderr,
        flush=True,
    )

    interface.open()
    try:
        interface.flush()
        runner(noop_program, tout=2.0)()
    finally:
        interface.close()

    if interface.validated_writes != len(expected_buffers):
        raise RuntimeError(
            "not all frozen RTLink writes were sent: "
            f"{interface.validated_writes}/{len(expected_buffers)}"
        )
    if interface.exceptions:
        raise RuntimeError(f"device exception reports: {interface.exceptions!r}")
    expected_completions = {(CHANNEL, node) for node in DESTINATION_NODES}
    if interface.completed != expected_completions:
        raise RuntimeError(
            "incomplete chassis-2 result: "
            f"expected {sorted(expected_completions)!r}, "
            f"got {sorted(interface.completed)!r}"
        )

    print(
        json.dumps(
            {
                "status": "passed",
                "case": fixture["case"],
                "validated_writes": interface.validated_writes,
                "completed": [
                    {"channel": channel, "node": node}
                    for channel, node in sorted(interface.completed)
                ],
                "exceptions": interface.exceptions,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
