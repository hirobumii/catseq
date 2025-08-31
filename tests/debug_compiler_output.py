
# tests/debug_compiler_output.py

from catseq.types import Board, Channel
from catseq.hardware.ttl import pulse
from catseq.lanes import merge_board_lanes
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.time_utils import cycles_to_us

def run_compiler_debug():
    """
    A debug script to trace the compilation of a parallel morphism with different durations.
    Traces: Morphism -> PhysicalLane (Intermediate Representation) -> OASM Calls
    """
    print("--- 启动编译器调试脚本 ---")
    print("目标: 验证 pulse(ch0, 100) | pulse(ch1, 150) 的编译流程\n")

    # 1. 设置硬件
    rwg0 = Board("RWG0")
    ch0 = Channel(rwg0, 0)
    ch1 = Channel(rwg0, 1)

    # 2. 构建 Morphism
    # pulse() is a high-level abstraction that creates:
    # ttl_on() >> wait() >> ttl_off()
    p0 = pulse(ch0, 100)
    p1 = pulse(ch1, 150)
    
    print("--- 1. 检查 Morphism 组合后的结构 ---")
    try:
        # The '|' operator should automatically pad the shorter pulse
        m = p0 | p1
        print("成功创建组合 Morphism: m = p0 | p1")
        print(m.lanes_view())
        
        p0_duration = p0.total_duration_us
        p1_duration = p1.total_duration_us
        m_duration = m.total_duration_us
        
        print(f"\n- Pulse 0 duration: {p0_duration}µs")
        print(f"- Pulse 1 duration: {p1_duration}µs")
        print(f"- Combined duration: {m_duration}µs")
        
        if m_duration == max(p0_duration, p1_duration):
            print("✅ (检查通过) 组合后的总时长正确。")
        else:
            print(f"❌ (检查失败) 组合时长 ({m_duration}µs) 不等于最长脉冲时长 ({max(p0_duration, p1_duration)}µs)。")

    except Exception as e:
        print(f"❌ 在构建 Morphism 时出错: {e}")
        return

    print("\n--- 2. 检查中间表示 (PhysicalLane) ---")
    try:
        board_lanes = m.lanes_by_board().get(rwg0)
        if not board_lanes:
            print("❌ (检查失败) 无法按板卡获取 lanes。")
            return
            
        physical_lane = merge_board_lanes(rwg0, board_lanes)
        print("成功生成 PhysicalLane (带绝对时间戳的事件列表):")
        
        print(f"Board: {physical_lane.board.id}")
        print("Events:")
        for op in physical_lane.operations:
            op_type = op.operation.operation_type.name
            op_ch = op.operation.channel.local_id
            op_time_us = cycles_to_us(op.timestamp_cycles)
            print(f"  - t={op_time_us:5.1f}µs: {op_type} on ch{op_ch}")
        
        # Manually verify the timestamps
        events = physical_lane.operations
        correct = (
            len(events) == 4 and
            events[0].timestamp_cycles == cycles_to_us(0) and events[0].operation.operation_type.name == 'TTL_ON' and
            events[1].timestamp_cycles == cycles_to_us(0) and events[1].operation.operation_type.name == 'TTL_ON' and
            events[2].timestamp_cycles == 100 * 250 and # 100us
            events[3].timestamp_cycles == 150 * 250 # 150us
        )
        # Note: The order of ON events at t=0 might vary, so a more robust check is needed in real tests.
        # For this debug script, visual inspection is key.

    except Exception as e:
        print(f"❌ 在生成中间表示时出错: {e}")
        return

    print("\n--- 3. 检查最终编译器输出 (OASM Calls) ---")
    try:
        # Note: The compiler in the project has print statements that will show the merge process.
        oasm_calls = compile_to_oasm_calls(m)
        print("\n成功生成 OASM 调用列表:")
        
        if not oasm_calls:
            print("❌ (检查失败) 编译器没有生成任何 OASM 调用。")
            return

        for call in oasm_calls:
            args_str = ", ".join(map(str, call.args))
            # Format mask and value as binary for clarity
            if call.dsl_func.name == 'TTL_SET' and len(call.args) == 2:
                mask, value = call.args
                args_str = f"mask=0b{mask:02b}, value=0b{value:02b}"

            print(f"  - {call.adr.value}.{call.dsl_func.name}({args_str})")
        
        print("\n✅ (检查通过) 编译器成功生成了 OASM 调用。")

    except Exception as e:
        print(f"❌ 在编译 OASM 调用时出错: {e}")
        return

    print("\n--- 调试脚本执行完毕 ---")


if __name__ == "__main__":
    run_compiler_debug()
