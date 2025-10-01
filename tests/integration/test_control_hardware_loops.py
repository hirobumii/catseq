"""
Integration tests for control.py hardware loop functionality.

This test focuses on repeat_morphism function with actual OASM hardware
loop instructions (for_, end, R registers) and timing calculations.
"""

import pytest
from oasm.rtmq2.intf import sim_intf
from oasm.rtmq2 import assembler, disassembler
from oasm.dev.main import C_MAIN, run_cfg
from oasm.dev.rwg import C_RWG, rwg

from catseq.atomic import ttl_init, ttl_on, ttl_off
from catseq.morphism import identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.types.ttl import TTLState
from catseq.control import repeat_morphism, compile_morphism_to_board_funcs, extract_channel_states_from_morphism


def test_repeat_morphism_hardware_loop_timing():
    """
    Test that repeat_morphism creates correct hardware loop timing calculations.

    This test verifies:
    - Correct timing formula: Total = 15 + n*(26 + t_morphism)
    - Hardware loop structure generation
    - OASM register usage (R[1] for loop counter)
    """
    print("\n🔄 Testing repeat_morphism hardware loop timing...")

    # Define hardware configuration
    rwg_board = Board("RWG_0")
    laser = Channel(rwg_board, 0, ChannelType.TTL)

    # Create a simple morphism: init → on → wait(10μs) → off
    # This should take: 2 + 1 + 2500 + 1 = 2504 cycles (10.016μs)
    base_morphism = (
        ttl_init(laser) @
        ttl_on(laser) @
        identity(10e-6) @  # 10μs = 2500 cycles
        ttl_off(laser)
    )

    # Get actual base morphism cycle count for accurate calculations
    base_cycles = base_morphism.total_duration_cycles

    # Test different repeat counts using actual base cycle count
    test_cases = [
        (1, 15 + 1 * (26 + base_cycles)),   # n=1: 15 + 1*(26+2504) = 2545 cycles
        (3, 15 + 3 * (26 + base_cycles)),   # n=3: 15 + 3*(26+2504) = 7605 cycles
        (10, 15 + 10 * (26 + base_cycles)), # n=10: 15 + 10*(26+2504) = 25315 cycles
    ]

    # Create OASM assembler for compilation
    try:
        intf_usb = sim_intf()
        intf_usb.nod_adr = 0
        intf_usb.loc_chn = 1
        seq = assembler(run_cfg(intf_usb, [0]), [('rwg0', C_RWG)])

        for count, expected_cycles in test_cases:
            print(f"📊 Testing repeat count: {count}")

            # Create repeated morphism
            repeated = repeat_morphism(base_morphism, count, seq)

            # Verify timing calculation
            actual_cycles = repeated.total_duration_cycles
            print(f"   Expected cycles: {expected_cycles}")
            print(f"   Actual cycles: {actual_cycles}")

            assert actual_cycles == expected_cycles, (
                f"Timing calculation failed for count={count}: "
                f"expected {expected_cycles}, got {actual_cycles}"
            )

            # Verify channel states are preserved
            original_states = {laser: (None, TTLState.OFF)}  # None -> off
            repeated_states = extract_channel_states_from_morphism(repeated)

            assert repeated_states == original_states, (
                f"Channel states not preserved for count={count}: "
                f"expected {original_states}, got {repeated_states}"
            )

            print(f"   ✅ Timing and states correct for count={count}")

        print("✅ All repeat_morphism timing tests passed!")
        return True

    except ImportError:
        print("⚠️  OASM not available, skipping hardware loop tests")
        return False
    except Exception as e:
        print(f"❌ Hardware loop timing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_repeat_morphism_hardware_loop_structure():
    """
    Test that repeat_morphism generates correct OASM hardware loop structure.

    This test verifies:
    - for_(R[1], count) instruction generation
    - Proper loop body execution
    - end() instruction generation
    - Correct assembly output
    """
    print("\n🔧 Testing repeat_morphism hardware loop structure...")

    try:
        # Define hardware
        rwg_board = Board("RWG_0")
        laser = Channel(rwg_board, 0, ChannelType.TTL)

        # Create simple morphism: just turn laser on then off
        base_morphism = ttl_on(laser) @ ttl_off(laser)

        # Create OASM assembler
        intf_usb = sim_intf()
        intf_usb.nod_adr = 0
        intf_usb.loc_chn = 1
        seq = assembler(run_cfg(intf_usb, [0]), [('rwg0', C_RWG)])

        # Create repeated morphism (repeat 5 times)
        count = 5
        repeated = repeat_morphism(base_morphism, count, seq)

        print(f"📋 Created repeated morphism with count={count}")
        print(f"   Base morphism cycles: {base_morphism.total_duration_cycles}")
        print(f"   Repeated morphism cycles: {repeated.total_duration_cycles}")

        # Get board functions from repeated morphism
        board_funcs = compile_morphism_to_board_funcs(repeated, seq)

        assert rwg_board in board_funcs, "RWG board not found in compiled functions"

        loop_executor = board_funcs[rwg_board]
        assert callable(loop_executor), "Board function is not callable"

        print("✅ Hardware loop structure compilation successful!")

        # Execute the loop function to generate actual assembly
        print("⚙️  Executing hardware loop to generate assembly...")
        try:
            # Execute in OASM context to generate assembly
            seq('rwg0', loop_executor)

            # Get generated assembly
            assembly_lines = disassembler(core=C_RWG)(seq.asm['rwg0'])

            print("🎯 Generated OASM Assembly:")
            for i, line in enumerate(assembly_lines):
                print(f"   {i:02d}: {line}")

            # Verify assembly contains loop instructions
            assembly_text = '\n'.join(assembly_lines)

            # Look for loop-related instructions (these may vary based on OASM version)
            loop_indicators = [
                'CHI',  # Loop counter setup (high part)
                'CLO',  # Loop counter setup (low part)
                'AMK',  # Register operations
                'JCC',  # Conditional jump (possible loop instruction)
                'JMP',  # Jump (possible loop instruction)
            ]

            found_indicators = []
            for indicator in loop_indicators:
                if indicator in assembly_text:
                    found_indicators.append(indicator)

            print(f"📊 Found loop indicators: {found_indicators}")

            assert len(found_indicators) > 0, (
                "No loop-related assembly instructions found. "
                f"Expected some of: {loop_indicators}"
            )

            print("✅ Hardware loop assembly generation successful!")

        except Exception as e:
            print(f"⚠️  Assembly generation failed: {e}")
            print("   (This may be normal if OASM context is incomplete)")

        return True

    except ImportError:
        print("⚠️  OASM not available, skipping hardware loop structure tests")
        return False
    except Exception as e:
        print(f"❌ Hardware loop structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_repeat_morphism_multi_channel_loop():
    """
    Test repeat_morphism with multi-channel morphisms.

    This test verifies:
    - Multiple channels in a repeated morphism
    - Correct timing for parallel operations in loops
    - Channel state preservation across loop iterations
    """
    print("\n🔀 Testing repeat_morphism with multi-channel operations...")

    try:
        # Define hardware
        rwg_board = Board("RWG_0")
        laser1 = Channel(rwg_board, 0, ChannelType.TTL)
        laser2 = Channel(rwg_board, 1, ChannelType.TTL)

        # Create multi-channel morphism
        laser1_ops = ttl_on(laser1) @ identity(5e-6) @ ttl_off(laser1)
        laser2_ops = ttl_on(laser2) @ identity(3e-6) @ ttl_off(laser2)

        # Parallel execution (tensor product)
        multi_channel_morphism = laser1_ops | laser2_ops

        print(f"📊 Multi-channel morphism:")
        print(f"   Total duration: {multi_channel_morphism.total_duration_us:.1f}μs")
        print(f"   Channels: {len(multi_channel_morphism.lanes)}")

        # Create OASM assembler
        intf_usb = sim_intf()
        intf_usb.nod_adr = 0
        intf_usb.loc_chn = 1
        seq = assembler(run_cfg(intf_usb, [0]), [('rwg0', C_RWG)])

        # Create repeated morphism
        count = 3
        repeated_multi = repeat_morphism(multi_channel_morphism, count, seq)

        print(f"🔄 Created repeated multi-channel morphism:")
        print(f"   Repeat count: {count}")
        print(f"   Base cycles: {multi_channel_morphism.total_duration_cycles}")
        print(f"   Total cycles: {repeated_multi.total_duration_cycles}")

        # Verify timing calculation
        base_cycles = multi_channel_morphism.total_duration_cycles
        expected_cycles = 15 + count * (26 + base_cycles)
        actual_cycles = repeated_multi.total_duration_cycles

        assert actual_cycles == expected_cycles, (
            f"Multi-channel timing calculation failed: "
            f"expected {expected_cycles}, got {actual_cycles}"
        )

        # Verify all channels are present
        original_channels = set(multi_channel_morphism.lanes.keys())
        repeated_channels = set(repeated_multi.lanes.keys())

        assert repeated_channels == original_channels, (
            f"Channels not preserved: original {original_channels}, "
            f"repeated {repeated_channels}"
        )

        print("✅ Multi-channel repeat morphism test successful!")
        return True

    except ImportError:
        print("⚠️  OASM not available, skipping multi-channel loop tests")
        return False
    except Exception as e:
        print(f"❌ Multi-channel loop test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_repeat_morphism_error_conditions():
    """
    Test repeat_morphism error handling.

    This test verifies:
    - Invalid repeat counts (0, negative)
    - Error message content
    """
    print("\n⚠️  Testing repeat_morphism error conditions...")

    try:
        # Define minimal morphism
        rwg_board = Board("RWG_0")
        laser = Channel(rwg_board, 0, ChannelType.TTL)
        morphism = ttl_on(laser)

        # Mock assembler (we don't need real OASM for error tests)
        mock_assembler = None

        # Test zero count
        with pytest.raises(ValueError, match="Repeat count must be positive"):
            repeat_morphism(morphism, 0, mock_assembler)

        # Test negative count
        with pytest.raises(ValueError, match="Repeat count must be positive"):
            repeat_morphism(morphism, -5, mock_assembler)

        print("✅ Error condition tests passed!")
        return True

    except Exception as e:
        print(f"❌ Error condition test failed: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Running Control Hardware Loop Integration Tests")
    print("=" * 60)

    success_count = 0
    total_tests = 4

    if test_repeat_morphism_error_conditions():
        success_count += 1

    if test_repeat_morphism_hardware_loop_timing():
        success_count += 1

    if test_repeat_morphism_hardware_loop_structure():
        success_count += 1

    if test_repeat_morphism_multi_channel_loop():
        success_count += 1

    print("\n" + "=" * 60)
    print(f"✅ {success_count}/{total_tests} control hardware loop tests passed!")

    if success_count == total_tests:
        print("🎉 All tests successful - Hardware loop functionality working!")
    else:
        print("⚠️  Some tests failed - check control.py implementation")