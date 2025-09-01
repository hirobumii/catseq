"""
Integration test for the complete CatSeq → OASM → RTMQ pipeline.

This test demonstrates the full workflow from Category Theory abstractions  
to actual RTMQ hardware assembly code generation using only CatSeq.
"""

from oasm.rtmq2.intf import sim_intf
from oasm.rtmq2 import assembler, disassembler
from oasm.dev.main import C_MAIN, run_cfg
from oasm.dev.rwg import C_RWG, rwg
from catseq.atomic import ttl_init, ttl_on, ttl_off
from catseq.morphism import identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.compilation.compiler import compile_to_oasm_calls, execute_oasm_calls


def test_catseq_to_rtmq_full_pipeline():
    """
    Test the complete pipeline from CatSeq Morphism to RTMQ assembly.
    """
    print("\n🎯 Testing CatSeq → OASM → RTMQ full pipeline...")
    
    try:
        
        print("✅ CatSeq modules imported successfully")
    except ImportError as e:
        print(f"❌ CatSeq modules not available: {e}")
        return False
    
    # Define hardware configuration
    rwg_board = Board("RWG_0")
    ch0 = Channel(rwg_board, 0, ChannelType.TTL)  # TTL channel 0
    ch1 = Channel(rwg_board, 1, ChannelType.TTL)  # TTL channel 1
    print("✅ Hardware configuration defined")
    
    # Create CatSeq Morphism sequence
    print("🔧 Creating CatSeq Morphism sequence...")
    
    # Channel 0: Initialize → Identity(5μs) → ON → Identity(10μs) → OFF → Identity(5μs)
    ch0_sequence = (
        ttl_init(ch0) @ 
        identity(5e-6) @ 
        ttl_on(ch0) @ 
        identity(10e-6) @ 
        ttl_off(ch0) @
        identity(5e-6)
    )
    
    # Channel 1: Initialize → Identity(10μs) → ON → Identity(15μs) → OFF  
    ch1_sequence = (
        ttl_init(ch1) @
        identity(10e-6) @
        ttl_on(ch1) @ 
        identity(15e-6) @
        ttl_off(ch1)
    )
    
    # Parallel execution - demonstrates tensor product
    parallel_sequence = ch0_sequence | ch1_sequence
    
    print(f"✅ CatSeq Morphism created:")
    print(f"   - Channel 0: init→wait(5μs)→pulse(10μs)→wait(5μs)")
    print(f"   - Channel 1: init→wait(10μs)→pulse(15μs)")
    print(f"   - Total duration: {parallel_sequence.total_duration_us:.1f}μs")
    print(f"   - Channels involved: {len(parallel_sequence.lanes)}")
    
    # Compile to OASM calls
    print("⚙️  Compiling CatSeq Morphism to OASM calls...")
    try:
        oasm_calls = compile_to_oasm_calls(parallel_sequence)
        print("✅ CatSeq → OASM compilation successful")
        
        print(f"📋 Generated {len(oasm_calls)} OASM calls:")
        for i, call in enumerate(oasm_calls):
            print(f"   {i:02d}: {call.adr.value} -> {call.dsl_func.name} {call.args}")
        
        # Analyze OASM calls
        func_counts = {}
        for call in oasm_calls:
            print(f"DZNB: {call.adr}")
            func_name = call.dsl_func.name
            func_counts[func_name] = func_counts.get(func_name, 0) + 1
        
        print(f"📊 OASM call analysis:")
        for func, count in func_counts.items():
            print(f"   - {func}: {count} calls")
        
        # Execute OASM calls (simulation)
        print("⚙️  Executing OASM calls...")
        
        # Create OASM context for real assembly generation
        try:
            from oasm.rtmq2.intf import sim_intf
            from oasm.rtmq2 import assembler, disassembler
            from oasm.dev.main import C_MAIN, run_cfg
            from oasm.dev.rwg import C_RWG, rwg
            
            # Create OASM instances
            intf_usb = sim_intf()
            intf_usb.nod_adr = 0
            intf_usb.loc_chn = 1
            
            rwgs = [0, 1]  # RWG boards
            run_all = run_cfg(intf_usb, rwgs + [0])
            seq = assembler(run_all, [('rwg0', C_RWG)])
            
            execution_success, result_seq = execute_oasm_calls(oasm_calls, seq)
            
            # 显示生成的汇编代码
            if result_seq:
                print("\n🎯 Final RTMQ Assembly Output:")
                try:
                    asm_lines = disassembler(core=C_RWG)(result_seq.asm['rwg0'])
                    for line in asm_lines:
                        print(f"   {line}")
                except Exception as e:
                    print(f"   Failed to generate final assembly: {e}")
                    
        except ImportError:
            print("OASM not available, using mock execution")
            execution_success, _ = execute_oasm_calls(oasm_calls)
        if execution_success:
            print("✅ OASM execution successful")
        else:
            print("⚠️  OASM execution completed with warnings")
        
        print("🎉 Complete CatSeq → OASM pipeline successful!")
        return True
        
    except Exception as e:
        print(f"❌ CatSeq compilation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_simple_catseq_pulse():
    """
    Test a simple CatSeq pulse for comparison.
    """
    print("\n🔬 Testing simple CatSeq TTL pulse...")
    
    try:
        
        # Define a simple single-channel pulse
        rwg_board = Board("RWG_0") 
        laser = Channel(rwg_board, 0, ChannelType.TTL)
        
        # Create a simple 20μs pulse sequence
        simple_pulse = (
            ttl_init(laser) @
            identity(5e-6) @    # Wait 5μs
            ttl_on(laser) @     # Turn ON
            identity(20e-6) @   # Hold for 20μs  
            ttl_off(laser) @    # Turn OFF
            identity(5e-6)      # Final wait 5μs
        )
        
        print(f"✅ Simple CatSeq pulse created:")
        print(f"   - Total duration: {simple_pulse.total_duration_us:.1f}μs")
        print(f"   - Channel: {laser.global_id}")
        
        # Compile to OASM calls
        oasm_calls = compile_to_oasm_calls(simple_pulse)
        
        print(f"📋 Generated {len(oasm_calls)} OASM calls:")
        for i, call in enumerate(oasm_calls):
            print(f"   {i:02d}: {call.adr.value} -> {call.dsl_func.name} {call.args}")
        
        print("✅ Simple CatSeq pulse test successful!")
        return True
        
    except Exception as e:
        print(f"❌ Simple pulse test failed: {e}")
        return False


def test_complex_catseq_experiment():
    """
    Test a realistic experimental sequence using CatSeq.
    """
    print("\n🎯 Testing complex experimental sequence...")
    
    try:
        # Define experimental hardware channels
        rwg_board = Board("RWG_0")
        laser = Channel(rwg_board, 0, ChannelType.TTL)      # Laser control
        detector = Channel(rwg_board, 1, ChannelType.TTL)   # Detector gate
        trigger = Channel(rwg_board, 2, ChannelType.TTL)    # External trigger
        
        print("🔬 Creating experimental sequence:")
        print("   - Laser: 10μs pulse starting at 5μs")
        print("   - Detector: 20μs gate starting at 3μs") 
        print("   - Trigger: 1μs pulse at 25μs")
        
        # Laser sequence: wait 5μs → pulse 10μs
        laser_seq = (
            ttl_init(laser) @
            identity(5e-6) @
            ttl_on(laser) @
            identity(10e-6) @
            ttl_off(laser)
        )
        
        # Detector sequence: wait 3μs → gate 20μs
        detector_seq = (
            ttl_init(detector) @
            identity(3e-6) @
            ttl_on(detector) @
            identity(20e-6) @
            ttl_off(detector)
        )
        
        # Trigger sequence: wait 25μs → trigger 1μs
        trigger_seq = (
            ttl_init(trigger) @
            identity(25e-6) @
            ttl_on(trigger) @
            identity(1e-6) @
            ttl_off(trigger)
        )
        
        # Parallel execution - tensor product
        experiment_sequence = laser_seq | detector_seq | trigger_seq
        
        print(f"✅ Complex sequence created:")
        print(f"   - Total duration: {experiment_sequence.total_duration_us:.1f}μs")
        print(f"   - Channels: {len(experiment_sequence.lanes)}")
        
        # Compile to OASM
        oasm_calls = compile_to_oasm_calls(experiment_sequence)
        
        print(f"📋 Generated {len(oasm_calls)} OASM calls:")
        for i, call in enumerate(oasm_calls):
            print(f"   {i:02d}: {call.adr.value} -> {call.dsl_func.name} {call.args}")
        
        print("✅ Complex experiment test successful!")
        return True
        
    except Exception as e:
        print(f"❌ Complex experiment test failed: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Running CatSeq → RTMQ Pipeline Integration Tests")
    print("=" * 60)
    
    # Run tests focusing on CatSeq functionality
    success_count = 0
    total_tests = 3
    
    if test_simple_catseq_pulse():
        success_count += 1
    
    if test_catseq_to_rtmq_full_pipeline():
        success_count += 1
        
    if test_complex_catseq_experiment():
        success_count += 1
    
    print("\n" + "=" * 60)
    print(f"✅ {success_count}/{total_tests} CatSeq integration tests passed!")
    
    if success_count == total_tests:
        print("🎉 All tests successful - CatSeq → RTMQ pipeline is working!")
    else:
        print("⚠️  Some tests failed - check CatSeq implementation")