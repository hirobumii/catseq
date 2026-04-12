"""
Direct CatSeq v2 compiler entrypoints.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import groupby

from catseq.compilation.types import OASMAddress, OASMCall, OASMFunction
from catseq.types.common import AtomicMorphism, OperationType
from catseq.types.rwg import RWGActive
from catseq.v2.morphism import Morphism, RealizedMorphism

from .schedule import ScheduleArena, lower_v2_morphism_to_schedule


def compile_v2_morphism_to_oasm_calls(
    morphism: Morphism | RealizedMorphism,
    start_states=None,
) -> dict[OASMAddress, list[OASMCall]]:
    schedule = lower_v2_morphism_to_schedule(morphism, start_states)
    return compile_schedule_to_oasm_calls(schedule)


def compile_schedule_to_oasm_calls(schedule: ScheduleArena) -> dict[OASMAddress, list[OASMCall]]:
    calls_by_board: dict[OASMAddress, list[OASMCall]] = {}
    if schedule.root_id is None:
        return calls_by_board

    root = schedule.nodes[schedule.root_id]
    for region_id in root.children:
        region = schedule.nodes[region_id]
        if region.board is None:
            continue
        address = OASMAddress(region.board.id.lower())
        board_calls: list[OASMCall] = []
        current_timestamp = 0
        timed_ops = [schedule.nodes[child_id] for child_id in region.children]
        for timestamp, op_group in groupby(timed_ops, key=lambda node: node.start_cycles):
            if timestamp > current_timestamp:
                board_calls.append(
                    OASMCall(
                        adr=address,
                        dsl_func=OASMFunction.WAIT,
                        args=(timestamp - current_timestamp,),
                    )
                )
                current_timestamp = timestamp
            operations = [
                node.operation
                for node in op_group
                if node.operation is not None
            ]
            board_calls.extend(_translate_group(address, operations))
        calls_by_board[address] = board_calls
    return calls_by_board


def _translate_group(address: OASMAddress, operations: list[AtomicMorphism]) -> list[OASMCall]:
    calls: list[OASMCall] = []
    ops_by_type: dict[OperationType, list[AtomicMorphism]] = defaultdict(list)
    for operation in operations:
        ops_by_type[operation.operation_type].append(operation)

    if OperationType.RWG_INIT in ops_by_type:
        calls.append(OASMCall(adr=address, dsl_func=OASMFunction.RWG_INIT))

    for operation in ops_by_type.get(OperationType.RWG_SET_CARRIER, []):
        assert operation.channel is not None
        calls.append(
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.RWG_SET_CARRIER,
                args=(operation.channel.local_id, operation.end_state.carrier_freq),
            )
        )

    for operation in ops_by_type.get(OperationType.RWG_RF_SWITCH, []):
        assert operation.channel is not None
        channel_mask = 1 << operation.channel.local_id
        state_mask = 0 if operation.end_state.rf_on else channel_mask
        calls.append(
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.RWG_RF_SWITCH,
                args=(channel_mask, state_mask),
            )
        )

    for operation in ops_by_type.get(OperationType.RWG_LOAD_COEFFS, []):
        if isinstance(operation.end_state, RWGActive) and operation.end_state.pending_waveforms:
            for waveform in operation.end_state.pending_waveforms:
                calls.append(
                    OASMCall(
                        adr=address,
                        dsl_func=OASMFunction.RWG_LOAD_WAVEFORM,
                        args=(waveform,),
                    )
                )

    if OperationType.RWG_UPDATE_PARAMS in ops_by_type:
        pud_mask = 0
        iou_mask = 0
        for operation in ops_by_type[OperationType.RWG_UPDATE_PARAMS]:
            assert operation.channel is not None
            channel_mask = 1 << operation.channel.local_id
            pud_mask |= channel_mask
            iou_mask |= channel_mask
        calls.append(
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.RWG_PLAY,
                args=(pud_mask, iou_mask),
            )
        )

    if OperationType.TTL_INIT in ops_by_type:
        mask = 0
        direction = 0
        for operation in ops_by_type[OperationType.TTL_INIT]:
            assert operation.channel is not None
            mask |= 1 << operation.channel.local_id
            if operation.end_state.value == 1:
                direction |= 1 << operation.channel.local_id
        calls.append(
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.TTL_CONFIG,
                args=(mask, direction),
            )
        )

    if OperationType.TTL_ON in ops_by_type or OperationType.TTL_OFF in ops_by_type:
        mask = 0
        state_value = 0
        for operation in ops_by_type.get(OperationType.TTL_ON, []):
            assert operation.channel is not None
            channel_mask = 1 << operation.channel.local_id
            mask |= channel_mask
            state_value |= channel_mask
        for operation in ops_by_type.get(OperationType.TTL_OFF, []):
            assert operation.channel is not None
            mask |= 1 << operation.channel.local_id
        if mask:
            board_type = "main" if address == OASMAddress.MAIN else "rwg"
            calls.append(
                OASMCall(
                    adr=address,
                    dsl_func=OASMFunction.TTL_SET,
                    args=(mask, state_value, board_type),
                )
            )

    if OperationType.SYNC_MASTER in ops_by_type:
        calls.append(
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.TRIG_SLAVE,
                args=(0, 12345),
            )
        )

    if OperationType.SYNC_SLAVE in ops_by_type:
        calls.append(
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.WAIT_MASTER,
                args=(12345,),
            )
        )

    return calls
