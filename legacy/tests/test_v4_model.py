import pytest
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.pending import PENDING
from catseq.states.rwg import RWGReady
from .helpers import StateA, StateB


# --- V4 Inference and Validation Tests ---


def test_successful_inference_on_composition(ch_rwg):
    """
    Tests that a pending `carrier_freq` in the second morphism's `dom`
    is correctly inferred from the first morphism's `cod`.
    """
    # M1: Ends in a state with a fully defined carrier_freq
    m1_cod_state = RWGReady(carrier_freq=100.0)
    m1 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "SetCarrier",
            dom=((ch_rwg, StateA()),),
            cod=((ch_rwg, m1_cod_state),),
            duration=1,
        )
    )

    # M2: Starts in a state with a PENDING carrier_freq
    m2_dom_template = RWGReady(carrier_freq=PENDING)
    m2_cod_state = RWGReady(carrier_freq=100.0)  # The cod should be consistent
    m2 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "DoSomething",
            dom=((ch_rwg, m2_dom_template),),
            cod=((ch_rwg, m2_cod_state),),
            duration=1,
        )
    )

    # Act: Compose the two morphisms
    result_seq = m1 @ m2

    # Assert: The composition was successful and the duration is correct
    assert result_seq.duration == 2.0

    # Assert: The dom of the second primitive in the resulting lane has been filled
    final_lane = result_seq.lanes[ch_rwg]
    assert len(final_lane) == 2
    second_prim = final_lane[1]

    inferred_dom_state = second_prim.dom[0][1]
    assert isinstance(inferred_dom_state, RWGReady)
    assert inferred_dom_state.carrier_freq == 100.0


def test_validation_fails_on_mismatched_explicit_state(ch_rwg):
    """
    Tests that composition fails if M2's dom has a specific but incorrect
    value for a parameter.
    """
    m1 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "SetCarrier100",
            dom=((ch_rwg, StateA()),),
            cod=((ch_rwg, RWGReady(100.0)),),
            duration=1,
        )
    )
    # M2's dom explicitly requires a different carrier_freq
    m2 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "Requires200",
            dom=((ch_rwg, RWGReady(200.0)),),
            cod=((ch_rwg, RWGReady(200.0)),),
            duration=1,
        )
    )

    with pytest.raises(TypeError, match="Invalid transition on channel RWG_0"):
        m1 @ m2


def test_validation_fails_on_insufficient_information(ch_rwg):
    """
    Tests that composition fails if M1.cod doesn't have the necessary
    information to fill M2.dom's pending field.
    """
    # M1 ends in a generic state that does NOT have a 'carrier_freq' attribute
    m1 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "GenericOp",
            dom=((ch_rwg, StateA()),),
            cod=((ch_rwg, StateB()),),
            duration=1,
        )
    )
    # M2 requires a 'carrier_freq' to be inferred
    m2 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "NeedsCarrier",
            dom=((ch_rwg, RWGReady(PENDING)),),
            cod=((ch_rwg, RWGReady(100.0)),),
            duration=1,
        )
    )

    with pytest.raises(TypeError, match="Invalid transition on channel RWG_0"):
        m1 @ m2


def test_composition_succeeds_with_no_pending_values(ch_rwg):
    """
    Tests that composition works as expected when there are no pending values
    and the states match perfectly.
    """
    m1 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "Set100",
            dom=((ch_rwg, StateA()),),
            cod=((ch_rwg, RWGReady(100.0)),),
            duration=1,
        )
    )
    m2 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "Use100",
            dom=((ch_rwg, RWGReady(100.0)),),
            cod=((ch_rwg, RWGReady(100.0)),),
            duration=1,
        )
    )

    result_seq = m1 @ m2
    assert result_seq.duration == 2.0
    assert result_seq.cod[0][1] == RWGReady(100.0)


def test_multi_channel_composition_with_inference(ch_rwg, ch_a):
    """
    Tests a multi-channel composition where one channel requires inference
    and the other is a simple pass-through.
    """
    # RWG Channel: Needs inference
    m_rwg1 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "Set100",
            dom=((ch_rwg, StateA()),),
            cod=((ch_rwg, RWGReady(100.0)),),
            duration=2,
        )
    )
    m_rwg2 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "UsePending",
            dom=((ch_rwg, RWGReady(PENDING)),),
            cod=((ch_rwg, RWGReady(100.0)),),
            duration=1,
        )
    )

    # TTL Channel: Simple composition
    m_ttl1 = LaneMorphism.from_primitive(
        PrimitiveMorphism(
            "TTL A->B", dom=((ch_a, StateA()),), cod=((ch_a, StateB()),), duration=1
        )
    )

    # Create a parallel morphism for the first step
    seq1 = m_rwg1 | m_ttl1
    assert seq1.duration == 2.0  # Check synchronization pad on TTL

    # Compose with the second RWG step
    result_seq = seq1 @ m_rwg2

    # Assertions
    assert result_seq.duration == 3.0

    # Check RWG channel was inferred correctly
    rwg_lane = result_seq.lanes[ch_rwg]
    assert rwg_lane[1].dom[0][1] == RWGReady(100.0)

    # Check TTL channel was padded correctly
    ttl_lane = result_seq.lanes[ch_a]
    # The lane should contain:
    # 1. The original TTL A->B primitive.
    # 2. The first padding morphism from the initial `|` operation.
    # 3. The second padding morphism from the final `@` operation.
    assert len(ttl_lane) == 3
    assert ttl_lane[2].name.startswith("Pad")
    assert ttl_lane[2].duration == 1.0
    assert result_seq.cod[1][1] == StateB()  # ch_a is sorted after rwg_ch
