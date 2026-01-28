"""CatSeq V2 - Compositional Quantum Control DSL

Three-phase Morphism architecture:
    OpenMorphism  ──(bind channel)──>  BoundMorphism  ──(bind state)──>  Morphism
      (template)                        (buffered)                      (compiled)

Example:
    >>> from catseq.v2.ttl import ttl_on, ttl_off, wait
    >>> from catseq.v2.morphism import parallel
    >>>
    >>> seq = ttl_on() >> wait(10*us) >> ttl_off()
    >>> bound = seq(channel)
    >>> result = bound({channel: TTLOff()})
"""

__version__ = "0.3.0"

from .morphism import (
    HardwareState,
    Morphism,
    BoundMorphism,
    OpenMorphism,
    parallel,
    encode_channel_id,
)

__all__ = [
    "__version__",
    "HardwareState",
    "Morphism",
    "BoundMorphism",
    "OpenMorphism",
    "parallel",
    "encode_channel_id",
]
