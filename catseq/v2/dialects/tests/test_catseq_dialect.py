"""Unit tests for CatSeq dialect types and operations."""

import pytest
from xdsl.dialects.builtin import IntegerAttr, StringAttr, DictionaryAttr, IntegerType

from catseq.v2.dialects.catseq_dialect import (
    ChannelType,
    StateType,
    MorphismType,
    ComposOp,
    TensorOp,
    IdentityOp,
    AtomicOp,
)


# ============================================================================
# Type Tests
# ============================================================================


class TestChannelType:
    """Test ChannelType construction and properties."""
    
    def test_channel_construction_with_strings_and_ints(self):
        """Test creating channel with string and int arguments."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        assert ch.get_board_type() == "rwg"
        assert ch.get_board_id() == 0
        assert ch.get_local_id() == 0
        assert ch.get_channel_type() == "ttl"
    
    def test_channel_construction_with_attrs(self):
        """Test creating channel with xDSL attribute objects."""
        board_type = StringAttr("main")
        board_id = IntegerAttr(0, IntegerType(32))
        local_id = IntegerAttr(5, IntegerType(32))
        channel_type = StringAttr("ttl")
        
        ch = ChannelType(board_type, board_id, local_id, channel_type)
        
        assert ch.get_board_type() == "main"
        assert ch.get_board_id() == 0
        assert ch.get_local_id() == 5
        assert ch.get_channel_type() == "ttl"
    
    def test_channel_global_id(self):
        """Test global channel ID generation."""
        ch1 = ChannelType("rwg", 0, 0, "ttl")
        assert ch1.get_global_id() == "RWG_0_TTL_0"
        
        ch2 = ChannelType("rwg", 1, 2, "rwg")
        assert ch2.get_global_id() == "RWG_1_RWG_2"
        
        ch3 = ChannelType("main", 0, 5, "ttl")
        assert ch3.get_global_id() == "MAIN_0_TTL_5"
    
    def test_channel_equality(self):
        """Test channel equality comparison."""
        ch1 = ChannelType("rwg", 0, 0, "ttl")
        ch2 = ChannelType("rwg", 0, 0, "ttl")
        ch3 = ChannelType("rwg", 0, 1, "ttl")
        
        assert ch1 == ch2
        assert ch1 != ch3
    
    def test_channel_hashable(self):
        """Test channels can be used in sets and dicts."""
        ch1 = ChannelType("rwg", 0, 0, "ttl")
        ch2 = ChannelType("rwg", 0, 1, "ttl")
        
        channel_set = {ch1, ch2}
        assert len(channel_set) == 2
        
        channel_dict = {ch1: "first", ch2: "second"}
        assert channel_dict[ch1] == "first"


class TestStateType:
    """Test StateType construction and properties."""
    
    def test_state_construction_ttl_off(self):
        """Test creating TTL OFF state."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        state_data = DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        state = StateType(ch, state_data)
        
        assert state.get_channel() == ch
        assert isinstance(state.get_state_data(), DictionaryAttr)
    
    def test_state_construction_ttl_on(self):
        """Test creating TTL ON state."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        state_data = DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        state = StateType(ch, state_data)
        
        assert state.get_channel() == ch
    
    def test_state_equality(self):
        """Test state equality (same channel, same data)."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        data1 = DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        data2 = DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        data3 = DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        
        state1 = StateType(ch, data1)
        state2 = StateType(ch, data2)
        state3 = StateType(ch, data3)
        
        assert state1 == state2  # Same channel, same data
        assert state1 != state3  # Same channel, different data


class TestMorphismType:
    """Test MorphismType construction and properties."""
    
    def test_morphism_construction(self):
        """Test creating a morphism (TTL OFF → ON)."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        off_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        )
        on_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        morphism = MorphismType(off_state, on_state, 1)
        
        assert morphism.get_domain() == off_state
        assert morphism.get_codomain() == on_state
        assert morphism.get_duration() == 1
        assert morphism.get_channel() == ch
    
    def test_morphism_with_integer_attr_duration(self):
        """Test morphism with IntegerAttr duration."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        duration = IntegerAttr(2500, IntegerType(64))
        morphism = MorphismType(state, state, duration)
        
        assert morphism.get_duration() == 2500
    
    def test_morphism_state_continuity_check(self):
        """Test state continuity verification."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        # Same channel: should pass
        morphism = MorphismType(state, state, 100)
        assert morphism.verify_state_continuity() is True


# ============================================================================
# Operation Tests
# ============================================================================


class TestAtomicOp:
    """Test AtomicOp construction."""
    
    def test_atomic_op_ttl_on(self):
        """Test creating ttl_on atomic operation."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        off_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        )
        on_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        ttl_on = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            domain=off_state,
            codomain=on_state,
            duration=1,
        )
        
        assert ttl_on.op_name.data == "ttl_on"
        assert ttl_on.result.type.get_duration() == 1
    
    def test_atomic_op_with_params(self):
        """Test atomic operation with parameters."""
        ch = ChannelType("rwg", 0, 0, "rwg")
        
        state1 = StateType(
            ch,
            DictionaryAttr({"frequency": IntegerAttr(0, IntegerType(32))})
        )
        state2 = StateType(
            ch,
            DictionaryAttr({"frequency": IntegerAttr(100, IntegerType(32))})
        )
        
        params = {"amplitude": IntegerAttr(50, IntegerType(32))}
        
        rwg_load = AtomicOp(
            op_name="rwg_load",
            channel=ch,
            domain=state1,
            codomain=state2,
            duration=10,
            params=params,
        )
        
        assert rwg_load.op_name.data == "rwg_load"
        assert isinstance(rwg_load.params, DictionaryAttr)


class TestIdentityOp:
    """Test IdentityOp construction."""
    
    def test_identity_op_wait(self):
        """Test creating wait (identity) operation."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        wait_op = IdentityOp(
            channel=ch,
            state=state,
            duration=2500,  # 10μs
        )
        
        assert wait_op.result.type.get_duration() == 2500
        # Identity: domain == codomain
        assert wait_op.result.type.get_domain() == wait_op.result.type.get_codomain()


class TestComposOp:
    """Test ComposOp (serial composition)."""
    
    def test_compos_op_valid(self):
        """Test valid composition: lhs.codomain == rhs.domain."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        off_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        )
        on_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        # Create ttl_on: OFF → ON
        ttl_on = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            domain=off_state,
            codomain=on_state,
            duration=1,
        )
        
        # Create wait: ON → ON
        wait_op = IdentityOp(
            channel=ch,
            state=on_state,
            duration=2500,
        )
        
        # Compose: ttl_on @ wait
        composed = ComposOp(ttl_on.result, wait_op.result)
        
        # Result should be: OFF → ON, duration = 1 + 2500
        assert composed.result.type.get_domain() == off_state
        assert composed.result.type.get_codomain() == on_state
        assert composed.result.type.get_duration() == 2501
    
    def test_compos_op_invalid_state_mismatch(self):
        """Test invalid composition: lhs.codomain != rhs.domain."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        off_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        )
        on_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        # Create ttl_on: OFF → ON
        ttl_on = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            domain=off_state,
            codomain=on_state,
            duration=1,
        )
        
        # Create another ttl_on: OFF → ON (wrong domain)
        ttl_on2 = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            domain=off_state,  # Should be on_state
            codomain=on_state,
            duration=1,
        )
        
        # Should fail verification
        with pytest.raises(ValueError, match="state continuity"):
            op = ComposOp(ttl_on.result, ttl_on2.result)
            op.verify_()


class TestTensorOp:
    """Test TensorOp (parallel composition)."""
    
    def test_tensor_op_valid_different_channels(self):
        """Test valid tensor product: different channels."""
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")
        
        off_state = DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        on_state = DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        
        # Channel 0: OFF → ON
        pulse0 = AtomicOp(
            op_name="ttl_on",
            channel=ch0,
            domain=StateType(ch0, off_state),
            codomain=StateType(ch0, on_state),
            duration=100,
        )
        
        # Channel 1: OFF → ON
        pulse1 = AtomicOp(
            op_name="ttl_on",
            channel=ch1,
            domain=StateType(ch1, off_state),
            codomain=StateType(ch1, on_state),
            duration=200,
        )
        
        # Tensor product: pulse0 | pulse1
        parallel = TensorOp(pulse0.result, pulse1.result)
        
        # Duration should be max(100, 200) = 200
        assert parallel.result.type.get_duration() == 200
    
    def test_tensor_op_invalid_same_channel(self):
        """Test invalid tensor product: same channel."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        off_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        )
        on_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        # Create two operations on same channel
        op1 = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            domain=off_state,
            codomain=on_state,
            duration=100,
        )
        
        op2 = AtomicOp(
            op_name="ttl_off",
            channel=ch,
            domain=on_state,
            codomain=off_state,
            duration=100,
        )
        
        # Should fail verification
        with pytest.raises(ValueError, match="disjoint channels"):
            op = TensorOp(op1.result, op2.result)
            op.verify_()


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Test realistic usage patterns."""
    
    def test_ttl_pulse_sequence(self):
        """Test creating a complete TTL pulse: init → on → wait → off."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        
        # Define states
        off_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        )
        on_state = StateType(
            ch,
            DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        )
        
        # Step 1: ttl_on (OFF → ON)
        ttl_on = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            domain=off_state,
            codomain=on_state,
            duration=1,
        )
        
        # Step 2: wait (ON → ON, 10μs = 2500 cycles)
        wait = IdentityOp(
            channel=ch,
            state=on_state,
            duration=2500,
        )
        
        # Step 3: ttl_off (ON → OFF)
        ttl_off = AtomicOp(
            op_name="ttl_off",
            channel=ch,
            domain=on_state,
            codomain=off_state,
            duration=1,
        )
        
        # Compose: ttl_on @ wait @ ttl_off
        seq1 = ComposOp(ttl_on.result, wait.result)
        pulse = ComposOp(seq1.result, ttl_off.result)
        
        # Verify final pulse
        assert pulse.result.type.get_domain() == off_state
        assert pulse.result.type.get_codomain() == off_state
        assert pulse.result.type.get_duration() == 2502  # 1 + 2500 + 1
    
    def test_parallel_pulses_different_channels(self):
        """Test parallel pulses on different channels."""
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")
        
        off_state_data = DictionaryAttr({"value": IntegerAttr(0, IntegerType(32))})
        on_state_data = DictionaryAttr({"value": IntegerAttr(1, IntegerType(32))})
        
        # Pulse on channel 0: 40μs
        pulse0 = AtomicOp(
            op_name="ttl_on",
            channel=ch0,
            domain=StateType(ch0, off_state_data),
            codomain=StateType(ch0, on_state_data),
            duration=10000,  # 40μs
        )
        
        # Pulse on channel 1: 20μs
        pulse1 = AtomicOp(
            op_name="ttl_on",
            channel=ch1,
            domain=StateType(ch1, off_state_data),
            codomain=StateType(ch1, on_state_data),
            duration=5000,  # 20μs
        )
        
        # Parallel: pulse0 | pulse1
        parallel = TensorOp(pulse0.result, pulse1.result)
        
        # Duration is max(10000, 5000) = 10000
        assert parallel.result.type.get_duration() == 10000
