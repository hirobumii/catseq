"""
CatSeq Dialect - High-Level Morphism Abstraction (Simplified)

This dialect represents quantum control operations using Category Theory concepts:
- Objects: System states (channel configurations)
- Morphisms: Time-bounded transformations on channels
- Composition: Serial execution (@)
- Tensor Product: Parallel execution (|)

Design Philosophy:
- catseq layer handles ONLY channels + duration
- State tracking deferred to qctrl/rtmq lowering passes
- Simplified type system for easier composition
"""

from __future__ import annotations

from typing import Sequence
from xdsl.ir import Dialect, ParametrizedAttribute, Attribute, SSAValue
from xdsl.irdl import (
    irdl_attr_definition,
    irdl_op_definition,
    IRDLOperation,
    param_def,
    operand_def,
    result_def,
    attr_def,
)
from xdsl.dialects.builtin import (
    IntegerAttr,
    StringAttr,
    ArrayAttr,
    IntegerType,
)


# ============================================================================
# Type Definitions
# ============================================================================


@irdl_attr_definition
class ChannelType(ParametrizedAttribute):
    """Physical channel identification.

    Syntax: !catseq.channel<board_type, board_id, local_id, channel_type>

    Examples:
        !catseq.channel<"rwg", 0, 0, "ttl">    // RWG_0, TTL channel 0
        !catseq.channel<"rwg", 1, 2, "rwg">    // RWG_1, RWG channel 2
        !catseq.channel<"main", 0, 5, "ttl">   // MAIN, TTL channel 5

    Board Types:
        - "rwg" : Radio Wave Generator boards
        - "main" : Main control board
        - "rsp" : Real-time Signal Processor boards

    Channel Types:
        - "ttl" : TTL (Transistor-Transistor Logic) channel
        - "rwg" : RWG waveform generation channel
        - "rsp" : RSP signal processing channel
    """

    name = "catseq.channel"

    board_type: StringAttr = param_def(StringAttr)
    board_id: IntegerAttr = param_def(IntegerAttr)
    local_id: IntegerAttr = param_def(IntegerAttr)
    channel_type: StringAttr = param_def(StringAttr)

    def __init__(
        self,
        board_type: str | StringAttr,
        board_id: int | IntegerAttr,
        local_id: int | IntegerAttr,
        channel_type: str | StringAttr,
    ):
        if isinstance(board_type, str):
            board_type = StringAttr(board_type)
        if isinstance(board_id, int):
            board_id = IntegerAttr(board_id, IntegerType(32))
        if isinstance(local_id, int):
            local_id = IntegerAttr(local_id, IntegerType(32))
        if isinstance(channel_type, str):
            channel_type = StringAttr(channel_type)

        super().__init__(board_type, board_id, local_id, channel_type)

    def get_board_type(self) -> str:
        """Get board type as string."""
        return self.board_type.data

    def get_board_id(self) -> int:
        """Get board ID as integer."""
        return self.board_id.value.data

    def get_local_id(self) -> int:
        """Get local channel ID as integer."""
        return self.local_id.value.data

    def get_channel_type(self) -> str:
        """Get channel type as string."""
        return self.channel_type.data

    def get_global_id(self) -> str:
        """Get global channel identifier.

        Format: "{BOARD_TYPE}_{BOARD_ID}_{CHANNEL_TYPE}_{LOCAL_ID}"
        Example: "RWG_0_TTL_0"
        """
        board_type = self.get_board_type().upper()
        board_id = self.get_board_id()
        channel_type = self.get_channel_type().upper()
        local_id = self.get_local_id()
        return f"{board_type}_{board_id}_{channel_type}_{local_id}"

    def __eq__(self, other: object) -> bool:
        """Channel equality based on all four components."""
        if not isinstance(other, ChannelType):
            return False
        return (
            self.board_type == other.board_type
            and self.board_id == other.board_id
            and self.local_id == other.local_id
            and self.channel_type == other.channel_type
        )

    def __hash__(self) -> int:
        return hash((
            self.board_type,
            self.board_id,
            self.local_id,
            self.channel_type,
        ))


@irdl_attr_definition
class MorphismType(ParametrizedAttribute):
    """Time-bounded transformation on a channel (simplified).

    Syntax: !catseq.morphism<channel, duration>

    Examples:
        // TTL operation on channel 0, 1 cycle (4ns @ 250MHz)
        !catseq.morphism<
            !catseq.channel<"rwg", 0, 0, "ttl">,
            1
        >

        // Wait operation, 2500 cycles (10μs)
        !catseq.morphism<
            !catseq.channel<"rwg", 0, 0, "ttl">,
            2500
        >

    Design Note:
        This simplified model removes state tracking from catseq layer.
        States are inferred during catseq → qctrl lowering.

    Time Unit: Clock cycles (250 MHz = 4ns per cycle)
    Conversion: 1μs = 250 cycles
    """

    name = "catseq.morphism"

    channel: ChannelType = param_def(ChannelType)
    duration: IntegerAttr = param_def(IntegerAttr)

    def __init__(
        self,
        channel: ChannelType,
        duration: int | IntegerAttr,
    ):
        if isinstance(duration, int):
            duration = IntegerAttr(duration, IntegerType(64))

        super().__init__(channel, duration)

    def get_channel(self) -> ChannelType:
        """Get the channel this morphism operates on."""
        return self.channel

    def get_duration(self) -> int:
        """Get duration in clock cycles."""
        return self.duration.value.data


@irdl_attr_definition
class CompositeMorphismType(ParametrizedAttribute):
    """Multi-channel morphism (result of tensor product).

    Syntax: !catseq.composite<[morphism1, morphism2, ...]>

    Examples:
        // Parallel operations on two channels
        !catseq.composite<[
            !catseq.morphism<!catseq.channel<"rwg", 0, 0, "ttl">, 100>,
            !catseq.morphism<!catseq.channel<"rwg", 0, 1, "ttl">, 200>
        ]>

    Design Note:
        This type represents the result of tensor product (|).
        All morphisms in the list must have disjoint channels.
        Duration is the maximum of all component durations (with auto-padding).
    """

    name = "catseq.composite"

    morphisms: ArrayAttr = param_def(ArrayAttr)

    def __init__(self, morphisms: list[MorphismType] | ArrayAttr):
        if isinstance(morphisms, list):
            morphisms = ArrayAttr(morphisms)

        super().__init__(morphisms)

    def get_morphisms(self) -> list[MorphismType]:
        """Get list of component morphisms."""
        return [m for m in self.morphisms.data]

    def get_channels(self) -> set[ChannelType]:
        """Get all channels involved in this composite morphism."""
        channels = set()
        for m in self.get_morphisms():
            assert isinstance(m, MorphismType)
            channels.add(m.get_channel())
        return channels

    def get_duration(self) -> int:
        """Get total duration (max of all component durations)."""
        return max(m.get_duration() for m in self.get_morphisms())


# ============================================================================
# Operations
# ============================================================================


@irdl_op_definition
class ComposOp(IRDLOperation):
    """Serial composition of morphisms (@).

    Syntax: %result = catseq.compos %lhs, %rhs

    Category Theory: Function composition (g ∘ f)
    Verification: Channels must be compatible
        - For simple morphisms: lhs.channel == rhs.channel
        - For composite morphisms: lhs.channels == rhs.channels
    Duration: lhs.duration + rhs.duration

    Supports:
        - MorphismType @ MorphismType → MorphismType
        - CompositeMorphismType @ CompositeMorphismType → CompositeMorphismType

    Example:
        // Simple: ttl_on @ wait @ ttl_off (all on same channel)
        %on = catseq.atomic<"ttl_on"> ...
        %wait = catseq.identity ...
        %off = catseq.atomic<"ttl_off"> ...
        %seq1 = catseq.compos %on, %wait
        %pulse = catseq.compos %seq1, %off

        // Composite: (A | B) @ (C | D) where A,C on ch0 and B,D on ch1
        %parallel1 = catseq.tensor %A, %B
        %parallel2 = catseq.tensor %C, %D
        %sequence = catseq.compos %parallel1, %parallel2
    """

    name = "catseq.compos"

    lhs = operand_def(MorphismType | CompositeMorphismType)
    rhs = operand_def(MorphismType | CompositeMorphismType)
    result = result_def(MorphismType | CompositeMorphismType)

    def __init__(self, lhs: SSAValue, rhs: SSAValue):
        lhs_type = lhs.type
        rhs_type = rhs.type

        # Case 1: Both are simple morphisms
        if isinstance(lhs_type, MorphismType) and isinstance(rhs_type, MorphismType):
            result_type = MorphismType(
                channel=lhs_type.get_channel(),
                duration=lhs_type.get_duration() + rhs_type.get_duration(),
            )

        # Case 2: Both are composite morphisms
        elif isinstance(lhs_type, CompositeMorphismType) and isinstance(rhs_type, CompositeMorphismType):
            # Compose each morphism pairwise (assuming channel alignment)
            lhs_morphisms = lhs_type.get_morphisms()
            rhs_morphisms = rhs_type.get_morphisms()

            # Create new morphisms with combined durations
            new_morphisms = []
            for lhs_m in lhs_morphisms:
                # Find corresponding rhs morphism with same channel
                matching_rhs = None
                for rhs_m in rhs_morphisms:
                    if lhs_m.get_channel() == rhs_m.get_channel():
                        matching_rhs = rhs_m
                        break

                if matching_rhs is None:
                    raise ValueError(f"No matching channel in rhs for {lhs_m.get_channel().get_global_id()}")

                # Compose: same channel, sum durations
                new_morphisms.append(MorphismType(
                    channel=lhs_m.get_channel(),
                    duration=lhs_m.get_duration() + matching_rhs.get_duration(),
                ))

            result_type = CompositeMorphismType(new_morphisms)

        # Case 3: Mixed types (not supported yet)
        else:
            raise ValueError(
                f"ComposOp requires both operands to be of same type "
                f"(both MorphismType or both CompositeMorphismType)"
            )

        super().__init__(
            operands=[lhs, rhs],
            result_types=[result_type],
        )

    def verify_(self) -> None:
        """Verify channel compatibility."""
        lhs_type = self.lhs.type
        rhs_type = self.rhs.type

        # Case 1: Both simple morphisms
        if isinstance(lhs_type, MorphismType) and isinstance(rhs_type, MorphismType):
            if lhs_type.get_channel() != rhs_type.get_channel():
                raise ValueError(
                    f"Composition requires same channel: "
                    f"lhs.channel = {lhs_type.get_channel().get_global_id()}, "
                    f"rhs.channel = {rhs_type.get_channel().get_global_id()}"
                )

        # Case 2: Both composite morphisms
        elif isinstance(lhs_type, CompositeMorphismType) and isinstance(rhs_type, CompositeMorphismType):
            lhs_channels = lhs_type.get_channels()
            rhs_channels = rhs_type.get_channels()

            if lhs_channels != rhs_channels:
                raise ValueError(
                    f"Composition requires same channel sets: "
                    f"lhs.channels = {[ch.get_global_id() for ch in lhs_channels]}, "
                    f"rhs.channels = {[ch.get_global_id() for ch in rhs_channels]}"
                )

        # Case 3: Mixed types
        else:
            raise ValueError(
                f"ComposOp requires both operands to be of same type"
            )


@irdl_op_definition
class TensorOp(IRDLOperation):
    """Parallel composition of morphisms (|).

    Syntax: %result = catseq.tensor %lhs, %rhs

    Category Theory: Tensor product (f ⊗ g)
    Verification: All channels must be disjoint (no overlap)
    Duration: max(all morphism durations) with automatic identity padding

    Supports:
        - MorphismType | MorphismType → CompositeMorphismType
        - MorphismType | CompositeMorphismType → CompositeMorphismType
        - CompositeMorphismType | MorphismType → CompositeMorphismType
        - CompositeMorphismType | CompositeMorphismType → CompositeMorphismType

    Example:
        // Simple: pulse1 | pulse2 (different channels)
        %pulse1 = ... // channel 0
        %pulse2 = ... // channel 1
        %parallel = catseq.tensor %pulse1, %pulse2

        // Recursive: (A | B) | C
        %parallel_ab = catseq.tensor %A, %B
        %parallel_abc = catseq.tensor %parallel_ab, %C
    """

    name = "catseq.tensor"

    lhs = operand_def(MorphismType | CompositeMorphismType)
    rhs = operand_def(MorphismType | CompositeMorphismType)
    result = result_def(CompositeMorphismType)

    def __init__(self, lhs: SSAValue, rhs: SSAValue):
        lhs_type = lhs.type
        rhs_type = rhs.type

        # Collect all morphisms from both operands
        all_morphisms = []

        # Extract morphisms from lhs
        if isinstance(lhs_type, MorphismType):
            all_morphisms.append(lhs_type)
        elif isinstance(lhs_type, CompositeMorphismType):
            all_morphisms.extend(lhs_type.get_morphisms())
        else:
            raise TypeError(f"Unexpected lhs type: {type(lhs_type)}")

        # Extract morphisms from rhs
        if isinstance(rhs_type, MorphismType):
            all_morphisms.append(rhs_type)
        elif isinstance(rhs_type, CompositeMorphismType):
            all_morphisms.extend(rhs_type.get_morphisms())
        else:
            raise TypeError(f"Unexpected rhs type: {type(rhs_type)}")

        # Create composite morphism with all morphisms
        result_type = CompositeMorphismType(all_morphisms)

        super().__init__(
            operands=[lhs, rhs],
            result_types=[result_type],
        )

    def verify_(self) -> None:
        """Verify all channels are disjoint (no tensor product with self)."""
        lhs_type = self.lhs.type
        rhs_type = self.rhs.type

        # Collect all channels from lhs
        lhs_channels = set()
        if isinstance(lhs_type, MorphismType):
            lhs_channels.add(lhs_type.get_channel())
        elif isinstance(lhs_type, CompositeMorphismType):
            lhs_channels = lhs_type.get_channels()

        # Collect all channels from rhs
        rhs_channels = set()
        if isinstance(rhs_type, MorphismType):
            rhs_channels.add(rhs_type.get_channel())
        elif isinstance(rhs_type, CompositeMorphismType):
            rhs_channels = rhs_type.get_channels()

        # Check for intersection
        intersection = lhs_channels & rhs_channels
        if intersection:
            raise ValueError(
                f"Tensor product requires disjoint channels, "
                f"but found overlapping channels: {[ch.get_global_id() for ch in intersection]}"
            )


@irdl_op_definition
class IdentityOp(IRDLOperation):
    """Identity morphism (wait/hold).

    Syntax: %result = catseq.identity %channel {duration = N} : !catseq.morphism<...>

    Category Theory: Identity morphism (id_A)
    Semantics: Maintain current state for specified duration

    Example:
        // wait(10μs) = 2500 cycles on channel 0
        %ch = !catseq.channel<"rwg", 0, 0, "ttl">
        %wait = catseq.identity %channel {duration = 2500}
    """

    name = "catseq.identity"

    channel = attr_def(ChannelType)
    duration = attr_def(IntegerAttr)
    result = result_def(MorphismType)

    def __init__(
        self,
        channel: ChannelType,
        duration: int | IntegerAttr,
    ):
        if isinstance(duration, int):
            duration = IntegerAttr(duration, IntegerType(64))

        result_type = MorphismType(
            channel=channel,
            duration=duration,
        )

        super().__init__(
            attributes={
                "channel": channel,
                "duration": duration,
            },
            result_types=[result_type],
        )


@irdl_op_definition
class AtomicOp(IRDLOperation):
    """Atomic operation (ttl_on, ttl_off, rwg_load, etc.).

    Syntax: %result = catseq.atomic<"op_name"> %channel {duration = N, params = <attr>}

    Atomic Operations:
        - "ttl_init" : Initialize TTL channel
        - "ttl_on" : Turn on TTL
        - "ttl_off" : Turn off TTL
        - "rwg_load" : Load RWG waveform
        - "rwg_play" : Play RWG waveform

    Example:
        // ttl_on(channel_0)
        %ch = !catseq.channel<"rwg", 0, 0, "ttl">
        %ttl_on = catseq.atomic<"ttl_on"> %channel {
            duration = 1,
            params = #catseq.ttl_state<...>
        }

    Note: params now accepts any Attribute type, enabling strong typing
          (e.g., StaticWaveformAttr, TTLStateAttr, etc.)
    """

    name = "catseq.atomic"

    op_name = attr_def(StringAttr)
    channel = attr_def(ChannelType)
    duration = attr_def(IntegerAttr)
    params = attr_def(Attribute)
    result = result_def(MorphismType)

    def __init__(
        self,
        op_name: str | StringAttr,
        channel: ChannelType,
        duration: int | IntegerAttr,
        params: Attribute | None = None,
    ):
        if isinstance(op_name, str):
            op_name = StringAttr(op_name)
        if isinstance(duration, int):
            duration = IntegerAttr(duration, IntegerType(64))
        if params is None:
            # Use empty string as default (xDSL requires an attribute)
            params = StringAttr("")

        result_type = MorphismType(
            channel=channel,
            duration=duration,
        )

        super().__init__(
            attributes={
                "op_name": op_name,
                "channel": channel,
                "duration": duration,
                "params": params,
            },
            result_types=[result_type],
        )


# ============================================================================
# Dialect Registration
# ============================================================================


class CatseqDialect(Dialect):
    """CatSeq dialect for high-level morphism abstractions."""

    name = "catseq"

    operations = frozenset([
        ComposOp,
        TensorOp,
        IdentityOp,
        AtomicOp,
    ])

    attributes = frozenset([
        ChannelType,
        MorphismType,
        CompositeMorphismType,
    ])
