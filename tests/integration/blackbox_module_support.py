"""Cross-module source fixture for public blackbox compilation tests."""

from catseq.morphism import Morphism
from catseq.oasm import black_box
from catseq.types import Board
from oasm.rtmq2 import nop


external_blackbox_board = Board("rwg0")


def emit_external_raw_oasm() -> None:
    nop(n=12)


def external_blackbox_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={external_blackbox_board: emit_external_raw_oasm},
    )
