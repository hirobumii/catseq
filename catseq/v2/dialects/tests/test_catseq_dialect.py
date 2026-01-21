"""Unit tests for CatSeq dialect types and operations (simplified)."""

import pytest
from xdsl.dialects.builtin import IntegerAttr, StringAttr, IntegerType

from catseq.v2.dialects.catseq_dialect import (
    ChannelType,
    MorphismType,
    CompositeMorphismType,
    ComposOp,
    TensorOp,
    IdentityOp,
    AtomicOp,
)


class TestChannelType:
    """Test ChannelType construction and properties."""

    def test_channel_construction_with_strings_and_ints(self):
        """Test creating channel with string and int arguments."""
        ch = ChannelType("rwg", 0, 0, "ttl")

        assert ch.get_board_type() == "rwg"
        assert ch.get_board_id() == 0
        assert ch.get_local_id() == 0
        assert ch.get_channel_type() == "ttl"

    def test_channel_global_id(self):
        """Test global channel ID generation."""
        ch1 = ChannelType("rwg", 0, 0, "ttl")
        assert ch1.get_global_id() == "RWG_0_TTL_0"

    def test_channel_equality(self):
        """Test channel equality comparison."""
        ch1 = ChannelType("rwg", 0, 0, "ttl")
        ch2 = ChannelType("rwg", 0, 0, "ttl")
        ch3 = ChannelType("rwg", 0, 1, "ttl")

        assert ch1 == ch2
        assert ch1 != ch3


class TestMorphismType:
    """Test MorphismType construction and properties."""

    def test_morphism_construction(self):
        """Test creating a simple morphism."""
        ch = ChannelType("rwg", 0, 0, "ttl")
        morphism = MorphismType(ch, 100)

        assert morphism.get_channel() == ch
        assert morphism.get_duration() == 100


class TestCompositeMorphismType:
    """Test CompositeMorphismType construction."""

    def test_composite_get_channels(self):
        """Test getting all channels from composite morphism."""
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")

        m0 = MorphismType(ch0, 100)
        m1 = MorphismType(ch1, 200)

        composite = CompositeMorphismType([m0, m1])
        channels = composite.get_channels()

        assert len(channels) == 2
        assert ch0 in channels
        assert ch1 in channels


class TestAtomicOp:
    """Test AtomicOp construction."""

    def test_atomic_op_ttl_on(self):
        """Test creating ttl_on atomic operation."""
        ch = ChannelType("rwg", 0, 0, "ttl")

        ttl_on = AtomicOp(
            op_name="ttl_on",
            channel=ch,
            duration=1,
        )

        assert ttl_on.op_name.data == "ttl_on"
        assert ttl_on.result.type.get_channel() == ch
        assert ttl_on.result.type.get_duration() == 1


class TestComposOp:
    """Test ComposOp (serial composition)."""

    def test_compos_op_simple_valid(self):
        """Test valid composition: same channel."""
        ch = ChannelType("rwg", 0, 0, "ttl")

        ttl_on = AtomicOp(op_name="ttl_on", channel=ch, duration=1)
        wait_op = IdentityOp(channel=ch, duration=2500)

        composed = ComposOp(ttl_on.result, wait_op.result)

        assert composed.result.type.get_channel() == ch
        assert composed.result.type.get_duration() == 2501

    def test_compos_op_composite_valid(self):
        """Test composition of composite morphisms: (A | B) @ (C | D)."""
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")

        # First parallel block: A | B
        opA = AtomicOp(op_name="ttl_on", channel=ch0, duration=100)
        opB = AtomicOp(op_name="ttl_on", channel=ch1, duration=100)
        parallel1 = TensorOp(opA.result, opB.result)

        # Second parallel block: C | D
        opC = AtomicOp(op_name="ttl_off", channel=ch0, duration=50)
        opD = AtomicOp(op_name="ttl_off", channel=ch1, duration=50)
        parallel2 = TensorOp(opC.result, opD.result)

        # Compose: (A | B) @ (C | D)
        composed = ComposOp(parallel1.result, parallel2.result)

        assert isinstance(composed.result.type, CompositeMorphismType)
        assert composed.result.type.get_duration() == 150


class TestTensorOp:
    """Test TensorOp (parallel composition)."""

    def test_tensor_op_simple_valid(self):
        """Test valid tensor product: different channels."""
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")

        pulse0 = AtomicOp(op_name="ttl_on", channel=ch0, duration=100)
        pulse1 = AtomicOp(op_name="ttl_on", channel=ch1, duration=200)

        parallel = TensorOp(pulse0.result, pulse1.result)

        assert isinstance(parallel.result.type, CompositeMorphismType)
        assert parallel.result.type.get_duration() == 200

    def test_tensor_op_recursive_valid(self):
        """Test recursive tensor product: (A | B) | C."""
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")
        ch2 = ChannelType("rwg", 0, 2, "ttl")

        opA = AtomicOp(op_name="ttl_on", channel=ch0, duration=100)
        opB = AtomicOp(op_name="ttl_on", channel=ch1, duration=200)
        parallelAB = TensorOp(opA.result, opB.result)

        opC = AtomicOp(op_name="ttl_on", channel=ch2, duration=150)
        parallelABC = TensorOp(parallelAB.result, opC.result)

        channels = parallelABC.result.type.get_channels()
        assert len(channels) == 3
