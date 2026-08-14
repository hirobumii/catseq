# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #80
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A nontrivial explicit ComputeFunction closure may use nested loops, fixed-point, if, and break.
# CONTRACT: CatSeq records one opaque Compute call while NAC3 owns the complete Mandelbrot CFG and SSA.
# CONTRACT: Its bounded cost is schedulable work and does not move the logical cursor.
# CONTRACT: fixed32[16] is a first-class Q16.16 type; raw int is not accepted as fixed-point.
# CONTRACT: Integer ratio constructors introduce no float value or Wasm float opcode.
# CONTRACT: A measurement seed keeps the grid calculation at Device availability.

from catseq import compute, control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import ms, us
from catseq.types import fixed32

from support.detectors import detector0
from support.hardware_map import correction_a


Q16_16 = fixed32[16]
FIXED_TWO = Q16_16.from_int(2)
ESCAPE_RADIUS_SQUARED = Q16_16.from_int(4)
GRID_WIDTH = 78
GRID_HEIGHT = 36
MAX_ITERATIONS = 16
MIN_X = Q16_16.from_int(-2)
MIN_Y = Q16_16.from_ratio(-18, 13)
X_STEP = Q16_16.from_ratio(1, 26)
Y_STEP = Q16_16.from_ratio(1, 13)


@compute
def escape_iterations(
    c_real: Q16_16,
    c_imag: Q16_16,
    max_iterations: int,
) -> int:
    z_real = c_real
    z_imag = c_imag
    iteration = 0
    while iteration < max_iterations:
        if z_real * z_real + z_imag * z_imag > ESCAPE_RADIUS_SQUARED:
            break
        next_real = z_real * z_real - z_imag * z_imag + c_real
        z_imag = FIXED_TWO * z_real * z_imag + c_imag
        z_real = next_real
        iteration = iteration + 1
    return iteration


@compute
def mandelbrot_checksum(seed: int) -> int:
    seed_bias = seed & 0xFF
    checksum = 0
    y = 0
    while y < GRID_HEIGHT:
        x = 0
        while x < GRID_WIDTH:
            c_real = MIN_X + Q16_16.from_int(x) * X_STEP
            c_imag = MIN_Y + Q16_16.from_int(y) * Y_STEP
            iterations = escape_iterations(c_real, c_imag, MAX_ITERATIONS)
            pixel_index = y * GRID_WIDTH + x + 1
            checksum = checksum + pixel_index * (iterations + 1) + seed_bias
            x = x + 1
        y = y + 1
    return checksum


@kernel
def sequence() -> Control:
    capture, seed = detector0.measure(1 * us)
    checksum = mandelbrot_checksum(seed)
    publish_result = control.branch(
        checksum & 1 == 0,
        when_true=identity(0) >> {correction_a: pulse(1 * us)},
        when_false=identity(0),
        join=control.fixed_end(20 * ms),
    )
    return capture >> publish_result
