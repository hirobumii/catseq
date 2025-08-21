# tests/test_model.py

import pytest
from catseq.model import Morphism

def test_sequential_composition_valid(dummy_channel_a, uninitialized_state, dummy_state_1):
    """测试合法的顺序组合"""
    m1 = Morphism(
        name="Init",
        dom=((dummy_channel_a, uninitialized_state),),
        cod=((dummy_channel_a, dummy_state_1),),
        duration=1.0,
        dynamics=None
    )
    m2 = Morphism(
        name="DoWork",
        dom=((dummy_channel_a, dummy_state_1),),
        cod=((dummy_channel_a, dummy_state_1),),
        duration=10.0,
        dynamics=None
    )
    
    composition = m1 @ m2
    
    assert composition.dom == m1.dom
    assert composition.cod == m2.cod
    assert composition.duration == 11.0

def test_sequential_composition_invalid_state_mismatch(dummy_channel_a, uninitialized_state, dummy_state_1, dummy_state_2):
    """测试因状态不匹配而导致的非法顺序组合"""
    m1 = Morphism(
        name="Init",
        dom=((dummy_channel_a, uninitialized_state),),
        cod=((dummy_channel_a, dummy_state_1),),
        duration=1.0,
        dynamics=None
    )
    m2 = Morphism(
        name="WrongWork",
        dom=((dummy_channel_a, dummy_state_2),),
        cod=((dummy_channel_a, dummy_state_2),),
        duration=10.0,
        dynamics=None
    )

    with pytest.raises(TypeError, match="State mismatch"):
        m1 @ m2

def test_parallel_composition_valid(dummy_channel_a, dummy_channel_b, dummy_state_1):
    """测试合法的并行组合"""
    m_a = Morphism(
        name="Op_A",
        dom=((dummy_channel_a, dummy_state_1),),
        cod=((dummy_channel_a, dummy_state_1),),
        duration=5.0,
        dynamics=None
    )
    m_b = Morphism(
        name="Op_B",
        dom=((dummy_channel_b, dummy_state_1),),
        cod=((dummy_channel_b, dummy_state_1),),
        duration=10.0,
        dynamics=None
    )

    tensor = m_a | m_b

    assert tensor.duration == 10.0
    assert len(tensor.dom) == 2
    assert len(tensor.cod) == 2

def test_parallel_composition_invalid_resource_conflict(dummy_channel_a, dummy_state_1):
    """测试因资源冲突而导致的非法并行组合"""
    m1 = Morphism(
        name="Op1_A",
        dom=((dummy_channel_a, dummy_state_1),),
        cod=((dummy_channel_a, dummy_state_1),),
        duration=5.0,
        dynamics=None
    )
    m2 = Morphism(
        name="Op2_A",
        dom=((dummy_channel_a, dummy_state_1),),
        cod=((dummy_channel_a, dummy_state_1),),
        duration=5.0,
        dynamics=None
    )
    
    with pytest.raises(TypeError, match="share common resources"):
        m1 | m2