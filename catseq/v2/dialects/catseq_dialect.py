"""
CatSeq Dialect - High-Level Morphism Abstraction

This dialect represents quantum control operations using Category Theory concepts:
- Objects: System states (channel configurations)
- Morphisms: State transformations (physical processes)
- Composition: Serial execution (@)
- Tensor Product: Parallel execution (|)

Design based on Monoidal Category Theory with strict verification rules.
"""

from __future__ import annotations

from typing import Sequence
from xdsl.ir import Dialect, ParametrizedAttribute, Data, Operation, SSAValue
from xdsl.irdl import (
    irdl_attr_definition,
    irdl_op_definition,
    IRDLOperation,
    param_def,
    operand_def,
    result_def,
    region_def,
    attr_def,
    VarOperand,
)
from xdsl.dialects.builtin import (
    IntegerAttr,
    StringAttr,
    DictionaryAttr,
    ArrayAttr,
    IntegerType,
)
from xdsl.parser import Parser
from xdsl.printer import Printer


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
class StateType(ParametrizedAttribute):
    """Channel state at a specific time.
    
    Syntax: !catseq.state<channel, state_data>
    
    Examples:
        // TTL OFF state
        !catseq.state<
            !catseq.channel<"rwg", 0, 0, "ttl">,
            {value = 0 : i32}
        >
        
        // TTL ON state
        !catseq.state<
            !catseq.channel<"rwg", 0, 0, "ttl">,
            {value = 1 : i32}
        >
        
        // RWG waveform state
        !catseq.state<
            !catseq.channel<"rwg", 0, 0, "rwg">,
            {
                frequency = 100.0 : f64,
                amplitude = 0.5 : f64,
                phase = 0.0 : f64
            }
        >
    
    State Data Schemas:
        TTL: {value: 0 or 1}
        RWG: {frequency, amplitude, phase}
        RSP: {threshold, gain}
    """
    
    name = "catseq.state"
    
    channel: ChannelType = param_def(ChannelType)
    state_data: DictionaryAttr = param_def(DictionaryAttr)
    
    def __init__(
        self,
        channel: ChannelType,
        state_data: DictionaryAttr | dict,
    ):
        if isinstance(state_data, dict):
            # Convert dict to DictionaryAttr
            state_data = DictionaryAttr(state_data)
        
        super().__init__(channel, state_data)
    
    def get_channel(self) -> ChannelType:
        """Get the channel this state refers to."""
        return self.channel
    
    def get_state_data(self) -> DictionaryAttr:
        """Get the state data dictionary."""
        return self.state_data
    
    def __eq__(self, other: object) -> bool:
        """State equality requires same channel and same state data."""
        if not isinstance(other, StateType):
            return False
        return (
            self.channel == other.channel
            and self.state_data == other.state_data
        )
    
    def __hash__(self) -> int:
        return hash((self.channel, self.state_data))


@irdl_attr_definition
class MorphismType(ParametrizedAttribute):
    """State transformation (morphism in Category Theory).
    
    Syntax: !catseq.morphism<domain, codomain, duration>
    
    Examples:
        // TTL pulse: OFF → ON, 1 cycle (4ns @ 250MHz)
        !catseq.morphism<
            !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 0}>,
            !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 1}>,
            1
        >
        
        // Wait: ON → ON, 2500 cycles (10μs)
        !catseq.morphism<
            !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 1}>,
            !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 1}>,
            2500
        >
    
    Time Unit: Clock cycles (250 MHz = 4ns per cycle)
    Conversion: 1μs = 250 cycles
    """
    
    name = "catseq.morphism"
    
    domain: StateType = param_def(StateType)
    codomain: StateType = param_def(StateType)
    duration: IntegerAttr = param_def(IntegerAttr)
    
    def __init__(
        self,
        domain: StateType,
        codomain: StateType,
        duration: int | IntegerAttr,
    ):
        if isinstance(duration, int):
            duration = IntegerAttr(duration, IntegerType(64))
        
        super().__init__(domain, codomain, duration)
    
    def get_domain(self) -> StateType:
        """Get input state."""
        return self.domain
    
    def get_codomain(self) -> StateType:
        """Get output state."""
        return self.codomain
    
    def get_duration(self) -> int:
        """Get duration in clock cycles."""
        return self.duration.value.data
    
    def get_channel(self) -> ChannelType:
        """Get the channel this morphism operates on.
        
        Note: domain and codomain must have same channel (enforced by verification).
        """
        return self.domain.get_channel()
    
    def verify_state_continuity(self) -> bool:
        """Verify domain and codomain refer to same channel."""
        return self.domain.get_channel() == self.codomain.get_channel()


# ============================================================================
# Operations
# ============================================================================


@irdl_op_definition
class ComposOp(IRDLOperation):
    """Serial composition of morphisms (@).
    
    Syntax: %result = catseq.compos %lhs, %rhs : !catseq.morphism<...>
    
    Category Theory: Function composition (g ∘ f)
    Verification: lhs.codomain must equal rhs.domain (state continuity)
    Duration: lhs.duration + rhs.duration
    
    Example:
        // ttl_on @ wait @ ttl_off
        %on = catseq.atomic<"ttl_on"> ...
        %wait = catseq.identity ...
        %off = catseq.atomic<"ttl_off"> ...
        %seq1 = catseq.compos %on, %wait
        %pulse = catseq.compos %seq1, %off
    """
    
    name = "catseq.compos"
    
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
    
    def __init__(self, lhs: SSAValue, rhs: SSAValue):
        # Extract types
        lhs_type = lhs.type
        rhs_type = rhs.type
        
        assert isinstance(lhs_type, MorphismType)
        assert isinstance(rhs_type, MorphismType)
        
        # Result: domain of lhs, codomain of rhs, sum of durations
        result_type = MorphismType(
            domain=lhs_type.get_domain(),
            codomain=rhs_type.get_codomain(),
            duration=lhs_type.get_duration() + rhs_type.get_duration(),
        )
        
        super().__init__(
            operands=[lhs, rhs],
            result_types=[result_type],
        )
    
    def verify_(self) -> None:
        """Verify state continuity: lhs.codomain == rhs.domain."""
        lhs_type = self.lhs.type
        rhs_type = self.rhs.type
        
        assert isinstance(lhs_type, MorphismType)
        assert isinstance(rhs_type, MorphismType)
        
        if lhs_type.get_codomain() != rhs_type.get_domain():
            raise ValueError(
                f"Composition requires state continuity: "
                f"lhs.codomain = {lhs_type.get_codomain()}, "
                f"rhs.domain = {rhs_type.get_domain()}"
            )


@irdl_op_definition
class TensorOp(IRDLOperation):
    """Parallel composition of morphisms (|).
    
    Syntax: %result = catseq.tensor %lhs, %rhs : !catseq.morphism<...>
    
    Category Theory: Tensor product (f ⊗ g)
    Verification: Channels must be disjoint (no overlap)
    Duration: max(lhs.duration, rhs.duration) with automatic identity padding
    
    Example:
        // pulse1 | pulse2 (different channels)
        %pulse1 = ... // channel 0
        %pulse2 = ... // channel 1
        %parallel = catseq.tensor %pulse1, %pulse2
    """
    
    name = "catseq.tensor"
    
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
    
    def __init__(self, lhs: SSAValue, rhs: SSAValue):
        # For tensor product, we create a composite morphism type
        # This is a simplified representation; full implementation would
        # need a CompositeMorphismType or similar
        
        lhs_type = lhs.type
        rhs_type = rhs.type
        
        assert isinstance(lhs_type, MorphismType)
        assert isinstance(rhs_type, MorphismType)
        
        # For now, use a placeholder result type
        # In full implementation, this would be a product type
        max_duration = max(lhs_type.get_duration(), rhs_type.get_duration())
        
        # Use lhs domain/codomain as placeholder
        result_type = MorphismType(
            domain=lhs_type.get_domain(),
            codomain=lhs_type.get_codomain(),
            duration=max_duration,
        )
        
        super().__init__(
            operands=[lhs, rhs],
            result_types=[result_type],
        )
    
    def verify_(self) -> None:
        """Verify channels are disjoint (no tensor product with self)."""
        lhs_type = self.lhs.type
        rhs_type = self.rhs.type
        
        assert isinstance(lhs_type, MorphismType)
        assert isinstance(rhs_type, MorphismType)
        
        lhs_channel = lhs_type.get_channel()
        rhs_channel = rhs_type.get_channel()
        
        if lhs_channel == rhs_channel:
            raise ValueError(
                f"Tensor product requires disjoint channels, "
                f"but both operands use {lhs_channel.get_global_id()}"
            )


@irdl_op_definition
class IdentityOp(IRDLOperation):
    """Identity morphism (wait/hold).
    
    Syntax: %result = catseq.identity %channel {duration = N} : !catseq.morphism<...>
    
    Category Theory: Identity morphism (id_A)
    Semantics: Maintain current state for specified duration
    
    Example:
        // wait(10μs) = 2500 cycles
        %ch = ... // channel
        %state = ... // current state
        %wait = catseq.identity %channel {duration = 2500} : ...
    """
    
    name = "catseq.identity"
    
    channel = attr_def(ChannelType)
    state = attr_def(StateType)
    duration = attr_def(IntegerAttr)
    result = result_def(MorphismType)
    
    def __init__(
        self,
        channel: ChannelType,
        state: StateType,
        duration: int | IntegerAttr,
    ):
        if isinstance(duration, int):
            duration = IntegerAttr(duration, IntegerType(64))
        
        # Identity: domain == codomain
        result_type = MorphismType(
            domain=state,
            codomain=state,
            duration=duration,
        )
        
        super().__init__(
            attributes={
                "channel": channel,
                "state": state,
                "duration": duration,
            },
            result_types=[result_type],
        )


@irdl_op_definition
class AtomicOp(IRDLOperation):
    """Atomic operation (ttl_on, ttl_off, rwg_load, etc.).
    
    Syntax: %result = catseq.atomic<"op_name"> %channel {params = {...}} : !catseq.morphism<...>
    
    Atomic Operations:
        - "ttl_init" : Initialize TTL channel (any → OFF)
        - "ttl_on" : Turn on TTL (OFF → ON)
        - "ttl_off" : Turn off TTL (ON → OFF)
        - "rwg_load" : Load RWG waveform
        - "rwg_play" : Play RWG waveform
    
    Example:
        // ttl_on(channel_0)
        %ch = ... // !catseq.channel<"rwg", 0, 0, "ttl">
        %off_state = ... // {value = 0}
        %on_state = ... // {value = 1}
        %ttl_on = catseq.atomic<"ttl_on"> %channel {
            domain = %off_state,
            codomain = %on_state,
            duration = 1
        } : !catseq.morphism<...>
    """
    
    name = "catseq.atomic"
    
    op_name = attr_def(StringAttr)
    channel = attr_def(ChannelType)
    domain = attr_def(StateType)
    codomain = attr_def(StateType)
    duration = attr_def(IntegerAttr)
    params = attr_def(DictionaryAttr)
    result = result_def(MorphismType)
    
    def __init__(
        self,
        op_name: str | StringAttr,
        channel: ChannelType,
        domain: StateType,
        codomain: StateType,
        duration: int | IntegerAttr,
        params: dict | DictionaryAttr | None = None,
    ):
        if isinstance(op_name, str):
            op_name = StringAttr(op_name)
        if isinstance(duration, int):
            duration = IntegerAttr(duration, IntegerType(64))
        if params is None:
            params = DictionaryAttr({})
        elif isinstance(params, dict):
            params = DictionaryAttr(params)
        
        result_type = MorphismType(
            domain=domain,
            codomain=codomain,
            duration=duration,
        )
        
        super().__init__(
            attributes={
                "op_name": op_name,
                "channel": channel,
                "domain": domain,
                "codomain": codomain,
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
        StateType,
        MorphismType,
    ])
