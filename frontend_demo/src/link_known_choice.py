# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #61
# ENTRY: sequence
# EXPECT: accept
# LINK-BINDING: use_remote
# CONTRACT: Link-known explicit Choice keeps every arm in CanonicalProgram.
# CONTRACT: use_remote has base type bool; the compile request supplies bool @ Link.
# CONTRACT: Link projects an already-lowered guarded fragment without rebuilding Control.
# CONTRACT: Binding-specific capacity and board composition are revalidated.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a, correction_b


@kernel
def local_path() -> Morphism:
    return Id() >> {correction_a: pulse(2 * us)}


@kernel
def remote_path() -> Morphism:
    return Id() >> {correction_b: pulse(2 * us)}


@kernel
def sequence(use_remote: bool) -> Control:
    return control.branch(
        use_remote,
        when_true=remote_path(),
        when_false=local_path(),
        join=control.fixed_end(3 * us),
    )
