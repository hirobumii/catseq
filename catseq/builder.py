from typing import Callable, List, Self
from catseq.protocols import Channel, State
from catseq.model import LaneMorphism

class MorphismBuilder:
    """
    Represents a deferred-execution 'recipe' for a morphism.
    This class wraps a list of generator functions that can be composed and
    then executed to produce a final, concrete LaneMorphism.
    """
    def __init__(self, generators: List[Callable[[Channel, State], LaneMorphism]] | None = None, single_generator: Callable | None = None):
        """Initializes the builder with a list of generator functions."""
        if generators is not None:
            self._generators = generators
        elif single_generator is not None:
            self._generators = [single_generator]
        else:
            self._generators = []

    def __matmul__(self, other: Self) -> Self:
        """
        Composes this MorphismBuilder with another in series by concatenating
        their generator lists.
        """
        new_generators = self._generators + other._generators
        return MorphismBuilder(generators=new_generators)

    def __call__(self, channel: Channel, from_state: State | None = None) -> LaneMorphism:
        """
        Executes the stored sequence of generators to produce a concrete LaneMorphism.
        """
        from catseq.states.common import Uninitialized
        from catseq.model import LaneMorphism

        if from_state is None:
            from_state = Uninitialized()

        if not self._generators:
            return LaneMorphism(lanes={})

        # Execute the first generator to get the starting morphism
        current_morphism = self._generators[0](channel, from_state)

        # Iteratively compose the rest of the morphisms
        for generator in self._generators[1:]:
            # The next state is the cod of the last primitive in the current sequence
            next_from_state = current_morphism.lanes[channel][-1].cod[0][1]
            next_morphism_piece = generator(channel, next_from_state)
            current_morphism = current_morphism @ next_morphism_piece

        return current_morphism
