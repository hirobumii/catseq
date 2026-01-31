"""测试 CatSeq V2 Eager State Inference & Backpatching

验证：
- OpenMorphism.infer_state 值级状态推导
- _compose_infer_state 组合
- BoundMorphism >> 时 eager exit_state 计算
- BoundMorphism.__call__ 时 patch 解析
- linear_ramp backpatching（无显式 start）
- 状态不兼容时的错误检测
"""

import sys
sys.path.insert(0, "/home/tosaka/catseq")

from catseq.types.common import Board, Channel, ChannelType
from catseq.time_utils import us
from catseq.v2.context import reset_context, get_context
from catseq.v2.morphism import (
    HardwareState,
    OpenMorphism,
    BoundMorphism,
    Morphism,
    _compose_infer_state,
    _compose_transitions,
)
from catseq.v2.ttl import (
    ttl_init, ttl_on, ttl_off, wait,
    TTLUninitialized, TTLOff, TTLOn,
)
from catseq.v2.rwg import (
    rwg_init, set_carrier, load_coeffs, update_params, rf_switch,
    initialize, set_state, rf_on, rf_off, linear_ramp,
    RWGUninitialized, RWGReady, RWGActive,
    StaticWaveform, WaveformParams,
)
from catseq.v2.opcodes import OpCode


# =============================================================================
# Helper
# =============================================================================

def make_ch(board: str = "RWG_0", local_id: int = 0,
            ch_type: ChannelType = ChannelType.TTL) -> Channel:
    return Channel(Board(board), local_id, ch_type)


# =============================================================================
# infer_state 基本测试
# =============================================================================

def test_ttl_infer_state():
    """TTL 原子操作的 infer_state"""
    assert ttl_init()._infer_state(TTLUninitialized()) == TTLOff()
    assert ttl_on()._infer_state(TTLOff()) == TTLOn()
    assert ttl_off()._infer_state(TTLOn()) == TTLOff()


def test_wait_infer_state_is_none():
    """wait 是 passthrough，infer_state = None"""
    assert wait(10 * us)._infer_state is None


def test_rwg_infer_state():
    """RWG 原子操作的 infer_state"""
    s = rwg_init()._infer_state(RWGUninitialized())
    assert isinstance(s, RWGReady)
    assert s.carrier_freq == 0.0

    s = set_carrier(100.0)._infer_state(RWGReady(carrier_freq=0.0))
    assert isinstance(s, RWGReady)
    assert s.carrier_freq == 100.0

    s = rf_switch(True)._infer_state(RWGReady(carrier_freq=50.0))
    assert isinstance(s, RWGActive)
    assert s.carrier_freq == 50.0
    assert s.rf_on is True


# =============================================================================
# _compose_infer_state 测试
# =============================================================================

def test_compose_infer_state_both_none():
    assert _compose_infer_state(None, None) is None


def test_compose_infer_state_left_none():
    fn = lambda s: TTLOn()
    assert _compose_infer_state(None, fn) is fn


def test_compose_infer_state_right_none():
    fn = lambda s: TTLOn()
    assert _compose_infer_state(fn, None) is fn


def test_compose_infer_state_chain():
    """组合后的 infer_state 正确链式调用"""
    fn1 = lambda s: RWGReady(carrier_freq=100.0)
    fn2 = lambda s: RWGActive(carrier_freq=s.carrier_freq, rf_on=True)
    composed = _compose_infer_state(fn1, fn2)
    result = composed(RWGUninitialized())
    assert isinstance(result, RWGActive)
    assert result.carrier_freq == 100.0
    assert result.rf_on is True


# =============================================================================
# OpenMorphism >> 组合后的 infer_state
# =============================================================================

def test_composed_open_morphism_infer_state():
    """OpenMorphism >> 组合后 infer_state 正确传递"""
    seq = ttl_init() >> ttl_on()
    assert seq._infer_state is not None
    result = seq._infer_state(TTLUninitialized())
    assert result == TTLOn()


def test_composed_open_morphism_with_wait():
    """wait 不影响 infer_state"""
    seq = ttl_on() >> wait(10 * us) >> ttl_off()
    result = seq._infer_state(TTLOff())
    assert result == TTLOff()


def test_rwg_composed_infer_state():
    """RWG 组合操作的 infer_state"""
    seq = initialize(100.0)
    result = seq._infer_state(RWGUninitialized())
    assert isinstance(result, RWGReady)
    assert result.carrier_freq == 100.0


# =============================================================================
# OpenMorphism._chain 测试
# =============================================================================

def test_atomic_has_no_chain():
    """原子 OpenMorphism 没有 chain"""
    assert ttl_on()._chain is None


def test_composed_has_chain():
    """组合 OpenMorphism 有 chain"""
    seq = ttl_on() >> wait(10 * us) >> ttl_off()
    assert seq._chain is not None
    assert len(seq._chain) == 3


# =============================================================================
# BoundMorphism eager exit_state (>> 时计算)
# =============================================================================

def test_bound_rshift_eager_exit_state():
    """BoundMorphism >> 时如果左边有 concrete exit_state，右边应立即计算"""
    reset_context()
    ch = make_ch()

    b1 = ttl_init()(ch)
    b2 = ttl_on()(ch)

    # b1 还没有 concrete exit_state（没有 start_state）
    assert b1._exit_state[ch] is None

    # 物化 b1 以获得 concrete exit_state
    m1 = b1({ch: TTLUninitialized()})
    assert m1.end_states[ch] == TTLOff()

    # 重新构建：通过 bound >> bound
    reset_context()
    b1 = ttl_init()(ch)
    b2 = ttl_on()(ch)
    combined = b1 >> b2
    # exit_state 仍为 None（两边都没有 concrete state）
    assert combined._infer_fn[ch] is not None


def test_bound_rshift_with_concrete_state():
    """当左边的 exit_state 被 __call__ 设定后，>> 应传播"""
    reset_context()
    ch = make_ch()

    # 构建带 concrete exit_state 的 BoundMorphism
    # 通过直接设置来模拟
    b1 = ttl_init()(ch)
    b1._exit_state[ch] = TTLOff()  # 模拟已知

    b2 = ttl_on()(ch)
    combined = b1 >> b2

    # 右边的 exit_state 应被 eagerly 计算
    assert combined._exit_state[ch] == TTLOn()


# =============================================================================
# BoundMorphism.__call__ 时的 infer_fn 计算
# =============================================================================

def test_call_computes_exit_via_infer_fn():
    """__call__ 使用 infer_fn 从 start_state 推导 exit_state"""
    reset_context()
    ch = make_ch()

    bound = ttl_on()(ch)
    assert bound._exit_state[ch] is None  # 绑定时无 concrete state

    result = bound({ch: TTLOff()})
    assert result.end_states[ch] == TTLOn()


def test_call_uses_precomputed_exit():
    """__call__ 优先使用已计算的 exit_state"""
    reset_context()
    ch = make_ch()

    bound = ttl_on()(ch)
    bound._exit_state[ch] = TTLOn()  # 已预计算

    result = bound({ch: TTLOff()})
    assert result.end_states[ch] == TTLOn()


def test_call_passthrough_for_wait():
    """wait 的 infer_fn 为 None，__call__ 应回退到 start_state"""
    reset_context()
    ch = make_ch()

    bound = wait(10 * us)(ch)
    result = bound({ch: TTLOn()})
    assert result.end_states[ch] == TTLOn()

    result2 = bound({ch: TTLOff()})
    assert result2.end_states[ch] == TTLOff()


# =============================================================================
# Backpatching 测试
# =============================================================================

def test_callable_payload_creates_patch():
    """callable payload 应创建 PendingPatch"""
    reset_context()
    ch = make_ch(ch_type=ChannelType.RWG)

    target = [StaticWaveform(sbg_id=0, freq=200.0, amp=1.0)]
    ramp = linear_ramp(target, 10 * us)
    bound = ramp(ch)

    # linear_ramp 的第一个 yield 是 callable → 应有 patch
    assert len(bound._patches) == 1
    assert bound._patches[0].channel == ch


def test_patch_resolved_at_call():
    """patch 在 __call__ 时通过 pre_infer + start_state 解析"""
    reset_context()
    ch = make_ch(ch_type=ChannelType.RWG)

    target = [StaticWaveform(sbg_id=0, freq=200.0, amp=1.0)]
    seq = set_carrier(100.0) >> linear_ramp(target, 10 * us)
    bound = seq(ch)

    assert len(bound._patches) == 1

    result = bound({ch: RWGReady(carrier_freq=0.0)})
    # patch 被解析，end_state 正确
    assert isinstance(result.end_states[ch], RWGActive)
    assert result.end_states[ch].snapshot == (StaticWaveform(sbg_id=0, freq=200.0, amp=1.0, phase=0.0),)


def test_patch_resolved_at_rshift():
    """当左边有 concrete exit_state 时，patch 在 >> 时解析"""
    reset_context()
    ch = make_ch(ch_type=ChannelType.RWG)

    b_left = set_carrier(100.0)(ch)
    b_left._exit_state[ch] = RWGReady(carrier_freq=100.0)

    target = [StaticWaveform(sbg_id=0, freq=200.0, amp=1.0)]
    b_right = linear_ramp(target, 10 * us)(ch)
    assert len(b_right._patches) == 1

    combined = b_left >> b_right
    # patch 应在 >> 时被解析（left has concrete exit）
    assert len(combined._patches) == 0


def test_patch_pre_infer_correct():
    """pre_infer 应只包含 patch 之前的 infer_state"""
    reset_context()
    ch = make_ch(ch_type=ChannelType.RWG)

    # set_carrier(100) >> linear_ramp
    # linear_ramp 的 patch 的 pre_infer 应包含 set_carrier 的 infer
    target = [StaticWaveform(sbg_id=0, freq=200.0, amp=1.0)]
    seq = set_carrier(100.0) >> linear_ramp(target, 10 * us)
    bound = seq(ch)

    patch = bound._patches[0]
    assert patch.pre_infer is not None

    # pre_infer 应将 RWGReady(0) 转为 RWGReady(100)
    pre_state = patch.pre_infer(RWGReady(carrier_freq=0.0))
    assert isinstance(pre_state, RWGReady)
    assert pre_state.carrier_freq == 100.0


# =============================================================================
# linear_ramp backpatching 端到端
# =============================================================================

def test_linear_ramp_backpatch_e2e():
    """端到端: set_carrier(100) >> linear_ramp(200, 10us) 编译正确"""
    reset_context()
    ch = make_ch(ch_type=ChannelType.RWG)

    target = [StaticWaveform(sbg_id=0, freq=200.0, amp=1.0)]
    seq = set_carrier(100.0) >> linear_ramp(target, 10 * us)
    bound = seq(ch)
    result = bound({ch: RWGReady(carrier_freq=0.0)})

    events = result.compile()
    assert len(events) > 0

    # 验证包含 RWG_SET_CARRIER、RWG_LOAD_COEFFS、RWG_UPDATE_PARAMS 等操作码
    opcodes = [e[2] for e in events]
    assert OpCode.RWG_SET_CARRIER in opcodes
    assert OpCode.RWG_LOAD_COEFFS in opcodes
    assert OpCode.RWG_UPDATE_PARAMS in opcodes


def test_linear_ramp_with_set_state_e2e():
    """set_state >> linear_ramp 端到端"""
    reset_context()
    ch = make_ch(ch_type=ChannelType.RWG)

    start = [StaticWaveform(sbg_id=0, freq=10.0, amp=0.5)]
    target = [StaticWaveform(sbg_id=0, freq=20.0, amp=1.0)]

    seq = initialize(100.0) >> set_state(start) >> linear_ramp(target, 10 * us)
    bound = seq(ch)
    result = bound({ch: RWGUninitialized()})

    assert isinstance(result.end_states[ch], RWGActive)
    events = result.compile()
    assert len(events) > 0


# =============================================================================
# 状态不兼容错误检测
# =============================================================================

def test_open_morphism_transition_mismatch():
    """OpenMorphism >> 时 transition 不兼容应抛错"""
    try:
        _ = ttl_on() >> ttl_on()  # TTLOff→TTLOn >> TTLOff→TTLOn: codomain TTLOn ∉ domain {TTLOff}
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "mismatch" in str(e).lower() or "overlap" in str(e).lower()


def test_bound_rshift_state_incompatible():
    """BoundMorphism >> 时 exit/entry 不兼容应抛错"""
    reset_context()
    ch = make_ch()

    b1 = ttl_on()(ch)
    b1._exit_state[ch] = TTLOn()

    b2 = ttl_on()(ch)  # entry_req = {TTLOff}

    try:
        _ = b1 >> b2
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "不兼容" in str(e) or "incompatible" in str(e).lower()


def test_call_entry_check():
    """__call__ 时 start_state 类型不匹配应抛错"""
    reset_context()
    ch = make_ch()

    bound = ttl_on()(ch)  # entry_req = {TTLOff}

    try:
        _ = bound({ch: TTLOn()})  # TTLOn ∉ {TTLOff}
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "entry_req" in str(e) or "不在" in str(e)


# =============================================================================
# HardwareState 没有 evolve 方法
# =============================================================================

def test_hardware_state_no_evolve():
    """HardwareState 不应有 evolve 方法（SRP）"""
    assert not hasattr(TTLOff(), 'evolve')
    assert not hasattr(TTLOn(), 'evolve')
    assert not hasattr(RWGReady(carrier_freq=0.0), 'evolve')
    assert not hasattr(RWGActive(carrier_freq=0.0), 'evolve')


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("运行 V2 State Inference & Backpatching 测试...\n")

    tests = [
        # infer_state 基本
        test_ttl_infer_state,
        test_wait_infer_state_is_none,
        test_rwg_infer_state,
        # _compose_infer_state
        test_compose_infer_state_both_none,
        test_compose_infer_state_left_none,
        test_compose_infer_state_right_none,
        test_compose_infer_state_chain,
        # OpenMorphism 组合后 infer_state
        test_composed_open_morphism_infer_state,
        test_composed_open_morphism_with_wait,
        test_rwg_composed_infer_state,
        # _chain
        test_atomic_has_no_chain,
        test_composed_has_chain,
        # BoundMorphism eager exit_state
        test_bound_rshift_eager_exit_state,
        test_bound_rshift_with_concrete_state,
        # __call__ infer_fn
        test_call_computes_exit_via_infer_fn,
        test_call_uses_precomputed_exit,
        test_call_passthrough_for_wait,
        # Backpatching
        test_callable_payload_creates_patch,
        test_patch_resolved_at_call,
        test_patch_resolved_at_rshift,
        test_patch_pre_infer_correct,
        # linear_ramp e2e
        test_linear_ramp_backpatch_e2e,
        test_linear_ramp_with_set_state_e2e,
        # 错误检测
        test_open_morphism_transition_mismatch,
        test_bound_rshift_state_incompatible,
        test_call_entry_check,
        # SRP
        test_hardware_state_no_evolve,
    ]

    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")

    print(f"\n所有 {len(tests)} 个测试通过!")
