import pytest
from catseq.protocols import Channel, State
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.builder import MorphismBuilder
from .helpers import StateA, StateB, StateC

# --- Test Fixtures and Mocks ---


@pytest.fixture
def generator_a_to_b() -> MorphismBuilder:
    """A builder that creates a morphism from StateA to StateB."""

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        m = PrimitiveMorphism(
            "A->B",
            dom=((channel, from_state),),
            cod=((channel, StateB()),),
            duration=1.0,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator)


@pytest.fixture
def generator_b_to_c() -> MorphismBuilder:
    """A builder that creates a morphism from StateB to StateC."""

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        m = PrimitiveMorphism(
            "B->C",
            dom=((channel, from_state),),
            cod=((channel, StateC()),),
            duration=2.0,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator)


# --- Tests ---


def test_builder_init(generator_a_to_b):
    """Tests that the MorphismBuilder is initialized correctly."""
    assert isinstance(generator_a_to_b, MorphismBuilder)


def test_builder_call(generator_a_to_b, ch_a):
    """Tests that calling a builder executes its generator."""
    # Execute the builder by calling it
    morphism = generator_a_to_b(ch_a, from_state=StateA())

    assert isinstance(morphism, LaneMorphism)
    assert morphism.dom == ((ch_a, StateA()),)
    assert morphism.cod == ((ch_a, StateB()),)
    assert morphism.duration == 1.0


def test_builder_call_with_default_state(generator_a_to_b, ch_a):
    """Tests that calling without a from_state uses the default Uninitialized."""
    from catseq.states.common import Uninitialized

    # Execute without providing from_state
    morphism = generator_a_to_b(ch_a)

    assert morphism.dom == ((ch_a, Uninitialized()),)
    assert morphism.cod == ((ch_a, StateB()),)


def test_builder_composition(generator_a_to_b, generator_b_to_c, ch_a):
    """
    Tests that composing two builders with `@` and then calling the result
    produces a correctly chained sequence.
    """
    # 1. Compose the builders (recipes)
    composite_builder = generator_a_to_b @ generator_b_to_c

    assert isinstance(composite_builder, MorphismBuilder)

    # 2. Execute the composite builder
    final_morphism = composite_builder(ch_a, from_state=StateA())

    # 3. Verify the final result
    assert isinstance(final_morphism, LaneMorphism)
    # The final dom should be the start of the first builder
    assert final_morphism.dom == ((ch_a, StateA()),)
    # The final cod should be the end of the second builder
    assert final_morphism.cod == ((ch_a, StateC()),)
    # The duration should be the sum of both
    assert final_morphism.duration == pytest.approx(3.0)
    # The internal structure should have two primitives
    assert len(final_morphism.lanes[ch_a]) == 2
