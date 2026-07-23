#!/usr/bin/env python3
"""Capture the pinned OASM two-board Download protocol transcript.

This is an offline oracle tool. It records bytes emitted by the exact frozen
OASM package without opening a hardware transport. With no arguments it writes
the transcript to stdout. This self-contained runtime case does not execute
CatSeq source. ``--output`` may create a new fixture, but refuses to replace an
existing file.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
from typing import Any

import oasm.rtmq2 as rtmq2
from oasm.dev.rwg import C_RWG
from oasm.rtmq2.intf import base_intf


CATSEQ_COMMIT = "eab85d9cc3fb82072ccfe2abdd25f1cb2368d488"
CATSEQ_NEAREST_RELEASE_TAG = "v0.2.4"
CATSEQ_REFERENCE_BRANCH = "origin/release/0.2"
OASM_COMMIT = "33b6c2538509e70475b49de5bd5a13ef334d4387"
OASM_PACKAGE_VERSION = "0.1.21.post1"


def _sha256_words(words: list[int]) -> str:
    encoded = b"".join(word.to_bytes(4, "big") for word in words)
    return hashlib.sha256(encoded).hexdigest()


def _verify_oracle() -> None:
    distribution = metadata.distribution("oasm")
    if distribution.version != OASM_PACKAGE_VERSION:
        raise RuntimeError(
            "wrong OASM package version: "
            f"expected {OASM_PACKAGE_VERSION}, got {distribution.version}"
        )

    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is None:
        raise RuntimeError("OASM installation has no direct_url.json commit provenance")
    direct_url = json.loads(direct_url_text)
    installed_commit = direct_url.get("vcs_info", {}).get("commit_id")
    if installed_commit != OASM_COMMIT:
        raise RuntimeError(
            f"wrong OASM commit: expected {OASM_COMMIT}, got {installed_commit}"
        )


class _RecordingInterface(base_intf):
    def __init__(self) -> None:
        super().__init__()
        self.buffers: list[bytes] = []
        self.programs: list[list[int]] = []
        self.write_nodes: list[int] = []
        self.monitor_calls: list[list[int]] = []

    def open_device(self) -> None:
        self.dev = self

    def close_device(self) -> None:
        self.dev = None

    def set_timeout(self, tout: float) -> None:
        self.dev_tot = tout

    def _dev_wr(self, frame: bytes) -> None:
        self.buffers.append(bytes(frame))

    def _dev_rd(self) -> None:
        return None

    def write(
        self, flg: int, chn: int, adr: int, tag: int, payload: list[int]
    ) -> None:
        self.write_nodes.append(adr)
        self.programs.append(list(payload))
        super().write(flg, chn, adr, tag, payload)

    def monitor(self, nodes: list[int], tout: int) -> dict[int, list[int]]:
        self.monitor_calls.append(list(nodes))
        return {}


def _capture_download() -> tuple[
    _RecordingInterface, list[int], int, dict[str, dict[str, int]]
]:
    interface = _RecordingInterface()
    interface.nod_adr = 20
    interface.loc_chn = 0

    captured_ich_words: list[int] | None = None
    exception_handler_word: int | None = None
    ich_loader_start: int | None = None
    ich_loader_end: int | None = None
    original_ich_download = rtmq2.ich_dnld
    original_intf_send = rtmq2.intf_send

    def recording_ich_download(payloads: list[int], start: int = 0) -> None:
        nonlocal captured_ich_words, ich_loader_start, ich_loader_end
        if captured_ich_words is not None:
            raise RuntimeError("the oracle unexpectedly generated multiple ICH programs")
        captured_ich_words = list(payloads)
        ich_loader_start = len(rtmq2.asm)
        original_ich_download(payloads, start)
        ich_loader_end = len(rtmq2.asm)

    def recording_intf_send(*args: Any, **kwargs: Any) -> None:
        nonlocal exception_handler_word
        if kwargs.get("info") == 1:
            if exception_handler_word is not None:
                raise RuntimeError(
                    "the oracle unexpectedly emitted multiple exception handlers"
                )
            exception_handler_word = len(rtmq2.asm[:])
        original_intf_send(*args, **kwargs)

    def noop_program() -> None:
        rtmq2.nop(2)

    rtmq2.ich_dnld = recording_ich_download
    rtmq2.intf_send = recording_intf_send
    try:
        runner = rtmq2.run_cfg(
            interface,
            [2, 5],
            mon=[2, 5],
            chn=0,
            tag=0,
            core=C_RWG,
        )
        runner(noop_program)()
    finally:
        rtmq2.ich_dnld = original_ich_download
        rtmq2.intf_send = original_intf_send

    if captured_ich_words is None:
        raise RuntimeError("the oracle did not generate an ICH program")
    if ich_loader_start is None or ich_loader_end is None:
        raise RuntimeError("the oracle did not expose the ICH loader boundary")
    if exception_handler_word is None:
        raise RuntimeError("the oracle did not expose the exception handler word")
    if len(interface.programs) != 2 or interface.programs[0] != interface.programs[1]:
        raise RuntimeError("the two nodes did not receive one identical loader program each")
    if interface.monitor_calls != [[2, 5]]:
        raise RuntimeError(
            f"unexpected completion monitor calls: {interface.monitor_calls!r}"
        )

    loader_word_count = len(interface.programs[0])
    sections = {
        "loader_prologue": {"start": 0, "end": ich_loader_start},
        "ich_download": {"start": ich_loader_start, "end": ich_loader_end},
        "launch": {"start": ich_loader_end, "end": loader_word_count},
    }
    return interface, captured_ich_words, exception_handler_word, sections


def capture_transcript() -> dict[str, Any]:
    """Capture the deterministic transcript without opening a device."""

    _verify_oracle()
    interface, ich_words, exception_handler_word, loader_sections = (
        _capture_download()
    )
    loader_words = interface.programs[0]
    frame_size = rtmq2.C_BASE.RTLK["N_BYT"]

    writes: list[dict[str, Any]] = []
    for node, buffer in zip(interface.write_nodes, interface.buffers, strict=True):
        if len(buffer) % frame_size:
            raise RuntimeError("OASM emitted a partial RTLink frame")
        frames = [
            buffer[offset : offset + frame_size].hex()
            for offset in range(0, len(buffer), frame_size)
        ]
        for raw_hex in frames:
            flag, channel, address, tag, _ = rtmq2.unpack_frame(
                bytes.fromhex(raw_hex)
            )
            if (flag, channel, address, tag) != (4, 0, node, 0):
                raise RuntimeError(
                    "unexpected RTLink header: "
                    f"{(flag, channel, address, tag)!r} for node {node}"
                )
        writes.append(
            {
                "node": node,
                "byte_count": len(buffer),
                "frame_count": len(frames),
                "sha256": hashlib.sha256(buffer).hexdigest(),
                "frames": frames,
            }
        )

    return {
        "schema_version": 1,
        "case": "two_board_noop_download",
        "provenance": {
            "reference_pipeline": {
                "catseq_commit": CATSEQ_COMMIT,
                "catseq_nearest_release_tag": CATSEQ_NEAREST_RELEASE_TAG,
                "catseq_reference_branch": CATSEQ_REFERENCE_BRANCH,
                "oasm_commit": OASM_COMMIT,
                "oasm_package_version": OASM_PACKAGE_VERSION,
            },
            "capture": {
                "kind": "self_contained_oasm_runtime_protocol",
                "verified_components": ["oasm"],
                "catseq_source_executed": False,
            },
        },
        "input": {
            "execution_mode": "download",
            "core": "rwg",
            "program": "nop(2)",
            "host_node": 20,
            "channel": 0,
            "tag": 0,
            "destination_nodes": [2, 5],
        },
        "ich_program": {
            "word_count": len(ich_words),
            "exception_handler_word": exception_handler_word,
            "sha256": _sha256_words(ich_words),
            "words": [f"{word:08x}" for word in ich_words],
        },
        "loader_program": {
            "word_count": len(loader_words),
            "sha256": _sha256_words(loader_words),
            "sections": loader_sections,
            "words": [f"{word:08x}" for word in loader_words],
        },
        "rtlink": {
            "frame_size_bytes": frame_size,
            "monitor_nodes": interface.monitor_calls[0],
            "writes": writes,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="create a new transcript fixture instead of writing to stdout",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    rendered = json.dumps(capture_transcript(), indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
        return
    if args.output.exists():
        raise SystemExit(f"refusing to replace existing fixture: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)


if __name__ == "__main__":
    main()
