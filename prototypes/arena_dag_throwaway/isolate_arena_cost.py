"""PROTOTYPE ONLY: replay the real Rydberg node stream into an empty arena.

This isolates append/storage overhead from RB1 domain construction, state-query
consumers, compatibility Lane materialization, calibration I/O, and nested
compilation.  It intentionally fails when median replay time exceeds 1 ms.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import gc
import io
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns


WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "rb1-next"))
sys.path.insert(0, str(WORKSPACE / "catseq"))

from experiments.computing.rydberg_transfer import RydbergTransferExp  # noqa: E402
from oasm.dev.main import C_MAIN  # noqa: E402
from oasm.dev.rsp import C_RSP  # noqa: E402
from oasm.dev.rwg import C_RWG  # noqa: E402
from oasm.rtmq2 import assembler  # noqa: E402
from rb1system.abstract.params import ExpParams  # noqa: E402

from arena_runtime import (  # noqa: E402
    ATOMIC_LEAF,
    DEFERRED_APPLY,
    DEFERRED_BATCH,
    DEFERRED_CHANNEL,
    LEAF,
    REPEAT,
    MorphismArena,
    build_arena,
    install,
)


OFFLINE_NODES = (
    *((f"rwg{index}", C_RWG) for index in (0, 1, 2, 3, 4, 5, 8, 9)),
    *((f"rsp{index}", C_RSP) for index in (6, 7, 10, 11)),
    ("main", C_MAIN),
)


def _capture_real_arena() -> MorphismArena:
    sequence = assembler(None, list(OFFLINE_NODES))
    experiment = RydbergTransferExp(
        device_list=object(),
        execution_mode="simulation",
        repeat_count=1,
        scan_frequencies_mhz=(484.75,),
        scan_times_us=(0.35,),
    )
    experiment.seq = sequence
    params = ExpParams(
        {
            experiment.srs_frequency: 484.75,
            experiment.pulse_time: 0.35,
        }
    )
    install()
    with build_arena() as arena, redirect_stdout(io.StringIO()):
        experiment.build_sequence(params)
    return arena


def _replay(source: MorphismArena) -> MorphismArena:
    target = MorphismArena()
    for node_id, kind in enumerate(source.kinds):
        if kind == LEAF:
            replayed_id = target.add_leaf(source.payload[node_id])
        elif kind == ATOMIC_LEAF:
            replayed_id = target.add_atomic(source.payload[node_id])
        elif kind == DEFERRED_CHANNEL:
            definition, channel, start_state = source.payload[node_id]
            replayed_id = target.add_deferred_channel(
                definition,
                channel,
                start_state,
            )
        elif kind == DEFERRED_APPLY:
            operations, breadcrumbs = source.payload[node_id]
            replayed_id = target.add_deferred_apply(
                source.left[node_id],
                operations,
                breadcrumbs,
            )
        elif kind == DEFERRED_BATCH:
            replayed_id = target.add_deferred_batch(
                source.left[node_id],
                source.payload[node_id],
            )
        elif kind == REPEAT:
            count, assembler_sequence = source.payload[node_id]
            replayed_id = target.add_repeat(
                source.left[node_id],
                count,
                assembler_sequence,
            )
        else:
            replayed_id = target.add_binary(
                kind,
                source.left[node_id],
                source.right[node_id],
            )
            target.payload[replayed_id] = source.payload[node_id]
        if replayed_id != node_id:
            raise AssertionError("replay changed NodeId ordering")
    return target


def benchmark(repeats: int) -> tuple[float, MorphismArena]:
    source = _capture_real_arena()
    _replay(source)
    samples = []
    gc.disable()
    try:
        for _ in range(repeats):
            started = perf_counter_ns()
            replayed = _replay(source)
            samples.append(perf_counter_ns() - started)
            if len(replayed.kinds) != len(source.kinds):
                raise AssertionError("replay changed node count")
            del replayed
    finally:
        gc.enable()
    return median(samples) / 1_000_000, source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=101)
    parser.add_argument("--limit-ms", type=float, default=1.0)
    args = parser.parse_args()
    replay_ms, source = benchmark(args.repeats)
    print(f"nodes={len(source.kinds)}")
    print(f"median_storage_replay_ms={replay_ms:.6f}")
    print(f"limit_ms={args.limit_ms:.6f}")
    if replay_ms > args.limit_ms:
        raise SystemExit(
            f"RED: pure arena storage exceeds target by {replay_ms - args.limit_ms:.6f} ms"
        )
    print("GREEN: pure arena storage is within the 1 ms target")


if __name__ == "__main__":
    main()
