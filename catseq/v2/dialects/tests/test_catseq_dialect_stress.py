"""Stress tests for CatSeq dialect - deep nesting validation.

These tests verify that the dialect can handle deeply nested compositions
without stack overflow or performance issues.
"""

import pytest
import time
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


class TestDeepNesting:
    """Test deep nesting capabilities of CatSeq dialect."""

    def test_deep_serial_composition_10000_layers(self):
        """Test serial composition with 10000 layers: A @ B @ C @ ... @ Z."""
        print("\n[Deep Serial Test] Building 10000-layer chain...")

        ch = ChannelType("rwg", 0, 0, "ttl")

        # Start with first operation
        start_time = time.time()
        current = AtomicOp(op_name="init", channel=ch, duration=1)

        # Build 10000-layer deep chain
        depth = 10000
        for i in range(depth):
            next_op = IdentityOp(channel=ch, duration=1)
            current = ComposOp(current.result, next_op.result)

            # Progress indicator every 1000 layers
            if (i + 1) % 1000 == 0:
                elapsed = time.time() - start_time
                print(f"  Progress: {i+1}/{depth} layers built ({elapsed:.2f}s)")

        build_time = time.time() - start_time
        print(f"[Deep Serial Test] Build completed in {build_time:.2f}s")

        # Verify final result
        assert isinstance(current.result.type, MorphismType)
        assert current.result.type.get_channel() == ch
        assert current.result.type.get_duration() == 10001  # init(1) + 10000*wait(1)

        print(f"[Deep Serial Test] ✓ Verified 10000-layer chain")
        print(f"[Deep Serial Test] Final duration: {current.result.type.get_duration()} cycles")

    def test_deep_parallel_nesting_10000_layers(self):
        """Test recursive parallel composition with 10000 layers: (((...A | B) | C) | D) | ..."""
        print("\n[Deep Parallel Test] Building 10000-layer recursive parallel...")

        # Use different channels for each layer
        base_channel = ChannelType("rwg", 0, 0, "ttl")

        # Start with first operation
        start_time = time.time()
        current = AtomicOp(op_name="op_0", channel=base_channel, duration=100)

        # Build recursive parallel structure
        depth = 10000
        for i in range(1, depth + 1):
            # Create new channel for each new branch
            new_channel = ChannelType("rwg", 0, i, "ttl")
            new_op = AtomicOp(op_name=f"op_{i}", channel=new_channel, duration=100)

            # Tensor with accumulated structure
            current = TensorOp(current.result, new_op.result)

            # Progress indicator every 1000 layers
            if i % 1000 == 0:
                elapsed = time.time() - start_time
                print(f"  Progress: {i}/{depth} layers built ({elapsed:.2f}s)")

        build_time = time.time() - start_time
        print(f"[Deep Parallel Test] Build completed in {build_time:.2f}s")

        # Verify final result
        assert isinstance(current.result.type, CompositeMorphismType)

        # Should have 10001 channels (base + 10000 new)
        channels = current.result.type.get_channels()
        assert len(channels) == 10001

        # Duration should be max of all (all are 100)
        assert current.result.type.get_duration() == 100

        print(f"[Deep Parallel Test] ✓ Verified 10000-layer recursive parallel")
        print(f"[Deep Parallel Test] Total channels: {len(channels)}")

    def test_deep_mixed_composition_1000_layers(self):
        """Test mixed serial/parallel composition with 1000 layers.

        Pattern: (A @ B) | (C @ D), then repeat with result.
        """
        print("\n[Mixed Composition Test] Building 1000-layer mixed structure...")

        start_time = time.time()

        # Initial block: (op0 @ wait0) | (op1 @ wait1)
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        ch1 = ChannelType("rwg", 0, 1, "ttl")

        op0 = AtomicOp(op_name="init", channel=ch0, duration=10)
        wait0 = IdentityOp(channel=ch0, duration=10)
        serial0 = ComposOp(op0.result, wait0.result)

        op1 = AtomicOp(op_name="init", channel=ch1, duration=10)
        wait1 = IdentityOp(channel=ch1, duration=10)
        serial1 = ComposOp(op1.result, wait1.result)

        current = TensorOp(serial0.result, serial1.result)

        # Build 1000-layer deep mixed composition
        depth = 1000
        for i in range(depth):
            # Each iteration: current @ (new_block_ch0 | new_block_ch1)
            new_op0 = AtomicOp(op_name=f"op_{i}", channel=ch0, duration=5)
            new_wait0 = IdentityOp(channel=ch0, duration=5)
            new_serial0 = ComposOp(new_op0.result, new_wait0.result)

            new_op1 = AtomicOp(op_name=f"op_{i}", channel=ch1, duration=5)
            new_wait1 = IdentityOp(channel=ch1, duration=5)
            new_serial1 = ComposOp(new_op1.result, new_wait1.result)

            new_parallel = TensorOp(new_serial0.result, new_serial1.result)

            # Compose with accumulated structure
            current = ComposOp(current.result, new_parallel.result)

            # Progress indicator every 100 layers
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                print(f"  Progress: {i+1}/{depth} layers built ({elapsed:.2f}s)")

        build_time = time.time() - start_time
        print(f"[Mixed Composition Test] Build completed in {build_time:.2f}s")

        # Verify final result
        assert isinstance(current.result.type, CompositeMorphismType)

        channels = current.result.type.get_channels()
        assert len(channels) == 2  # Always ch0 and ch1

        # Duration: initial(20) + 1000 * block(10) = 10020
        expected_duration = 20 + (1000 * 10)
        assert current.result.type.get_duration() == expected_duration

        print(f"[Mixed Composition Test] ✓ Verified 1000-layer mixed structure")
        print(f"[Mixed Composition Test] Final duration: {current.result.type.get_duration()} cycles")

    def test_wide_parallel_10000_channels(self):
        """Test wide parallel composition with 10000 channels (breadth not depth)."""
        print("\n[Wide Parallel Test] Building 10000-channel parallel structure...")

        start_time = time.time()

        # Start with first operation
        ch0 = ChannelType("rwg", 0, 0, "ttl")
        current = AtomicOp(op_name="op_0", channel=ch0, duration=100)

        # Build wide structure with 10000 channels
        num_channels = 10000
        for i in range(1, num_channels):
            # Create new channel
            new_channel = ChannelType("rwg", 0, i, "ttl")
            new_op = AtomicOp(op_name=f"op_{i}", channel=new_channel, duration=100)

            # Add to parallel structure
            current = TensorOp(current.result, new_op.result)

            # Progress indicator every 1000 channels
            if i % 1000 == 0:
                elapsed = time.time() - start_time
                print(f"  Progress: {i}/{num_channels} channels added ({elapsed:.2f}s)")

        build_time = time.time() - start_time
        print(f"[Wide Parallel Test] Build completed in {build_time:.2f}s")

        # Verify final result
        assert isinstance(current.result.type, CompositeMorphismType)

        channels = current.result.type.get_channels()
        assert len(channels) == num_channels

        print(f"[Wide Parallel Test] ✓ Verified 10000-channel parallel structure")
        print(f"[Wide Parallel Test] Total channels: {len(channels)}")

    def test_verification_performance_deep_chain(self):
        """Test verification performance on deep chain."""
        print("\n[Verification Performance Test] Testing verification on deep chain...")

        ch = ChannelType("rwg", 0, 0, "ttl")

        # Build a 1000-layer chain
        depth = 1000
        current = AtomicOp(op_name="init", channel=ch, duration=1)

        for i in range(depth):
            next_op = IdentityOp(channel=ch, duration=1)
            current = ComposOp(current.result, next_op.result)

        # Test verification performance
        start_time = time.time()

        # Run verification 100 times
        iterations = 100
        for _ in range(iterations):
            current.verify_()

        verify_time = time.time() - start_time
        avg_time = verify_time / iterations

        print(f"[Verification Performance Test] Average verification time: {avg_time*1000:.2f}ms")
        print(f"[Verification Performance Test] ✓ Verification is fast enough")

        # Verify time should be reasonably fast (< 10ms per verification)
        assert avg_time < 0.01, f"Verification too slow: {avg_time*1000:.2f}ms"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_duration_operations(self):
        """Test operations with zero duration."""
        ch = ChannelType("rwg", 0, 0, "ttl")

        # Zero duration operation
        op = AtomicOp(op_name="instant", channel=ch, duration=0)

        assert op.result.type.get_duration() == 0

        # Compose with zero duration
        wait = IdentityOp(channel=ch, duration=100)
        composed = ComposOp(op.result, wait.result)

        assert composed.result.type.get_duration() == 100

    def test_single_operation_chain(self):
        """Test that single operations work correctly."""
        ch = ChannelType("rwg", 0, 0, "ttl")

        op = AtomicOp(op_name="single", channel=ch, duration=42)

        assert isinstance(op.result.type, MorphismType)
        assert op.result.type.get_duration() == 42
        assert op.result.type.get_channel() == ch

    def test_empty_composite_morphism(self):
        """Test composite morphism with minimal content."""
        ch = ChannelType("rwg", 0, 0, "ttl")

        m = MorphismType(ch, 100)
        composite = CompositeMorphismType([m])

        # Should work even with single morphism
        assert len(composite.get_morphisms()) == 1
        assert composite.get_duration() == 100


if __name__ == "__main__":
    # Run stress tests with verbose output
    pytest.main([__file__, "-v", "-s"])
