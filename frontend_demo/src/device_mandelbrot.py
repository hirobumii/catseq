# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A nontrivial pure realtime Kernel may use nested loops, fixed-point arithmetic, if, and break.
# CONTRACT: The entire Mandelbrot calculation remains NAC3 ComputeCFG with empty temporal topology.
# CONTRACT: Its bounded cost is schedulable work and does not move the logical cursor.
# CONTRACT: Device computation uses signed integer Q16.16 because RTMQ has no float arithmetic.
# CONTRACT: Grid divisions fold at Compile; Device code uses integer add, multiply, shift, and compare.
# CONTRACT: A measurement seed keeps the grid calculation at Device availability.
# CONTRACT: Seed zero on the fixed 78 by 36 grid produces checksum 26771162.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import ms, us

from support.detectors import detector0
from support.hardware_map import correction_a


FIXED_SHIFT = 16
FIXED_ONE = 1 << FIXED_SHIFT
ESCAPE_RADIUS_SQUARED = 4 * FIXED_ONE * FIXED_ONE
GRID_WIDTH = 78
GRID_HEIGHT = 36
MAX_ITERATIONS = 16
MIN_X = -2 * FIXED_ONE
MAX_X = FIXED_ONE
X_STEP = (MAX_X - MIN_X) // GRID_WIDTH
Y_SCALE = (MAX_X - MIN_X) * GRID_HEIGHT * 2 // GRID_WIDTH
Y_STEP = Y_SCALE // GRID_HEIGHT


@kernel
def fixed_multiply(left: int, right: int) -> int:
    return (left * right) >> FIXED_SHIFT


@kernel
def escape_iterations(
    c_real: int,
    c_imag: int,
    max_iterations: int,
) -> int:
    z_real = c_real
    z_imag = c_imag
    iteration = 0
    while iteration < max_iterations:
        if (
            z_real * z_real + z_imag * z_imag
            > ESCAPE_RADIUS_SQUARED
        ):
            break
        next_real = (
            fixed_multiply(z_real, z_real)
            - fixed_multiply(z_imag, z_imag)
            + c_real
        )
        z_imag = 2 * fixed_multiply(z_real, z_imag) + c_imag
        z_real = next_real
        iteration = iteration + 1
    return iteration


@kernel
def mandelbrot_checksum(seed: int) -> int:
    coordinate_jitter = seed & 0xFF
    checksum = 0
    y = 0
    while y < GRID_HEIGHT:
        x = 0
        while x < GRID_WIDTH:
            c_real = MIN_X + x * X_STEP + coordinate_jitter
            c_imag = y * Y_STEP - Y_SCALE // 2
            iterations = escape_iterations(c_real, c_imag, MAX_ITERATIONS)
            pixel_index = y * GRID_WIDTH + x + 1
            checksum = checksum + pixel_index * (iterations + 1)
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
