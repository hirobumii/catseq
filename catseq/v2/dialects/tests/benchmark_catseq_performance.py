"""Performance benchmarks for CatSeq dialect.

This module provides comprehensive performance measurements including:
- Build time vs depth/width
- Memory usage profiling
- Verification performance
- Scalability analysis
"""

import time
import sys
import gc
import tracemalloc
from dataclasses import dataclass
from typing import Callable

from catseq.v2.dialects.catseq_dialect import (
    ChannelType,
    MorphismType,
    CompositeMorphismType,
    ComposOp,
    TensorOp,
    IdentityOp,
    AtomicOp,
)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    name: str
    depth: int
    build_time: float
    memory_mb: float
    peak_memory_mb: float
    operations_per_sec: float
    verification_time: float = 0.0


class PerformanceBenchmark:
    """Performance benchmark suite for CatSeq dialect."""

    def __init__(self):
        self.results: list[BenchmarkResult] = []

    def run_benchmark(
        self,
        name: str,
        depth: int,
        build_fn: Callable[[], tuple],
    ) -> BenchmarkResult:
        """Run a single benchmark and collect metrics."""
        # Force garbage collection before measurement
        gc.collect()

        # Start memory tracking
        tracemalloc.start()

        # Measure build time
        start_time = time.time()
        result_op = build_fn()
        build_time = time.time() - start_time

        # Get memory usage
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        current_mb = current / 1024 / 1024
        peak_mb = peak / 1024 / 1024

        # Calculate operations per second
        ops_per_sec = depth / build_time if build_time > 0 else 0

        # Measure verification time (for ops with verify_)
        verification_time = 0.0
        if hasattr(result_op, 'verify_'):
            start_verify = time.time()
            try:
                result_op.verify_()
                verification_time = time.time() - start_verify
            except:
                pass

        result = BenchmarkResult(
            name=name,
            depth=depth,
            build_time=build_time,
            memory_mb=current_mb,
            peak_memory_mb=peak_mb,
            operations_per_sec=ops_per_sec,
            verification_time=verification_time,
        )

        self.results.append(result)
        return result

    def benchmark_serial_composition(self, depth: int) -> BenchmarkResult:
        """Benchmark serial composition: A @ B @ C @ ... @ Z."""
        def build():
            ch = ChannelType("rwg", 0, 0, "ttl")
            current = AtomicOp(op_name="init", channel=ch, duration=1)
            for i in range(depth):
                next_op = IdentityOp(channel=ch, duration=1)
                current = ComposOp(current.result, next_op.result)
            return current

        return self.run_benchmark(
            f"Serial Composition",
            depth,
            build,
        )

    def benchmark_recursive_parallel(self, depth: int) -> BenchmarkResult:
        """Benchmark recursive parallel: (((...A | B) | C) | D) | ..."""
        def build():
            base_channel = ChannelType("rwg", 0, 0, "ttl")
            current = AtomicOp(op_name="op_0", channel=base_channel, duration=100)

            for i in range(1, depth + 1):
                new_channel = ChannelType("rwg", 0, i, "ttl")
                new_op = AtomicOp(op_name=f"op_{i}", channel=new_channel, duration=100)
                current = TensorOp(current.result, new_op.result)

            return current

        return self.run_benchmark(
            f"Recursive Parallel",
            depth,
            build,
        )

    def benchmark_wide_parallel(self, width: int) -> BenchmarkResult:
        """Benchmark wide parallel with many channels."""
        def build():
            ch0 = ChannelType("rwg", 0, 0, "ttl")
            current = AtomicOp(op_name="op_0", channel=ch0, duration=100)

            for i in range(1, width):
                new_channel = ChannelType("rwg", 0, i, "ttl")
                new_op = AtomicOp(op_name=f"op_{i}", channel=new_channel, duration=100)
                current = TensorOp(current.result, new_op.result)

            return current

        return self.run_benchmark(
            f"Wide Parallel",
            width,
            build,
        )

    def benchmark_mixed_composition(self, depth: int) -> BenchmarkResult:
        """Benchmark mixed serial/parallel composition."""
        def build():
            ch0 = ChannelType("rwg", 0, 0, "ttl")
            ch1 = ChannelType("rwg", 0, 1, "ttl")

            # Initial block
            op0 = AtomicOp(op_name="init", channel=ch0, duration=10)
            wait0 = IdentityOp(channel=ch0, duration=10)
            serial0 = ComposOp(op0.result, wait0.result)

            op1 = AtomicOp(op_name="init", channel=ch1, duration=10)
            wait1 = IdentityOp(channel=ch1, duration=10)
            serial1 = ComposOp(op1.result, wait1.result)

            current = TensorOp(serial0.result, serial1.result)

            # Build deep mixed structure
            for i in range(depth):
                new_op0 = AtomicOp(op_name=f"op_{i}", channel=ch0, duration=5)
                new_wait0 = IdentityOp(channel=ch0, duration=5)
                new_serial0 = ComposOp(new_op0.result, new_wait0.result)

                new_op1 = AtomicOp(op_name=f"op_{i}", channel=ch1, duration=5)
                new_wait1 = IdentityOp(channel=ch1, duration=5)
                new_serial1 = ComposOp(new_op1.result, new_wait1.result)

                new_parallel = TensorOp(new_serial0.result, new_serial1.result)
                current = ComposOp(current.result, new_parallel.result)

            return current

        return self.run_benchmark(
            f"Mixed Composition",
            depth,
            build,
        )

    def print_result(self, result: BenchmarkResult):
        """Print a single benchmark result."""
        print(f"\n{'='*70}")
        print(f"Benchmark: {result.name} (depth={result.depth})")
        print(f"{'='*70}")
        print(f"  Build Time:        {result.build_time:.3f}s")
        print(f"  Memory (current):  {result.memory_mb:.2f} MB")
        print(f"  Memory (peak):     {result.peak_memory_mb:.2f} MB")
        print(f"  Ops/sec:           {result.operations_per_sec:.0f}")
        if result.verification_time > 0:
            print(f"  Verification:      {result.verification_time*1000:.2f}ms")
        print(f"{'='*70}")

    def print_summary(self):
        """Print summary of all benchmarks."""
        print("\n" + "="*70)
        print("PERFORMANCE SUMMARY")
        print("="*70)
        print(f"{'Test':<25} {'Depth':<8} {'Time(s)':<10} {'Mem(MB)':<10} {'Ops/s':<10}")
        print("-"*70)

        for result in self.results:
            print(f"{result.name:<25} {result.depth:<8} {result.build_time:<10.3f} "
                  f"{result.peak_memory_mb:<10.2f} {result.operations_per_sec:<10.0f}")

        print("="*70)


def run_scalability_test():
    """Test scalability with increasing depths."""
    print("\n" + "="*70)
    print("SCALABILITY TEST - Serial Composition")
    print("="*70)

    depths = [100, 500, 1000, 2000, 5000, 10000]
    results = []

    bench = PerformanceBenchmark()

    for depth in depths:
        result = bench.benchmark_serial_composition(depth)
        results.append(result)

        print(f"\nDepth: {depth:>6} | "
              f"Time: {result.build_time:>6.3f}s | "
              f"Memory: {result.peak_memory_mb:>6.2f}MB | "
              f"Ops/s: {result.operations_per_sec:>8.0f}")

    # Check if scaling is roughly linear
    print("\n" + "-"*70)
    print("Scaling Analysis:")
    for i in range(1, len(results)):
        depth_ratio = results[i].depth / results[i-1].depth
        time_ratio = results[i].build_time / results[i-1].build_time
        efficiency = time_ratio / depth_ratio

        print(f"  {results[i-1].depth} → {results[i].depth}: "
              f"depth×{depth_ratio:.1f}, time×{time_ratio:.2f}, "
              f"efficiency={efficiency:.2f} (ideal=1.0)")

    return results


def run_comparison_benchmarks():
    """Run comparison benchmarks for different patterns."""
    print("\n" + "="*70)
    print("PATTERN COMPARISON BENCHMARKS")
    print("="*70)

    bench = PerformanceBenchmark()

    # Test at depth=1000 for all patterns
    depth = 1000

    print("\n[1/4] Serial Composition...")
    r1 = bench.benchmark_serial_composition(depth)
    bench.print_result(r1)

    print("\n[2/4] Recursive Parallel...")
    r2 = bench.benchmark_recursive_parallel(depth)
    bench.print_result(r2)

    print("\n[3/4] Wide Parallel...")
    r3 = bench.benchmark_wide_parallel(depth)
    bench.print_result(r3)

    print("\n[4/4] Mixed Composition...")
    r4 = bench.benchmark_mixed_composition(depth)
    bench.print_result(r4)

    bench.print_summary()

    return bench.results


def run_extreme_stress_test():
    """Run extreme stress test with very deep nesting."""
    print("\n" + "="*70)
    print("EXTREME STRESS TEST")
    print("="*70)

    bench = PerformanceBenchmark()

    # Test serial composition up to 50,000 layers
    print("\n[Extreme Serial] Building 50,000-layer chain...")
    result = bench.benchmark_serial_composition(50000)
    bench.print_result(result)

    # Test parallel with 20,000 channels
    print("\n[Extreme Parallel] Building 20,000-channel structure...")
    result = bench.benchmark_recursive_parallel(20000)
    bench.print_result(result)

    return bench.results


def run_memory_profiling():
    """Profile memory usage patterns."""
    print("\n" + "="*70)
    print("MEMORY PROFILING")
    print("="*70)

    bench = PerformanceBenchmark()

    # Test memory growth with increasing depth
    depths = [1000, 5000, 10000, 20000]

    print("\nSerial Composition Memory Growth:")
    print(f"{'Depth':<10} {'Memory (MB)':<15} {'Per-Op (KB)':<15}")
    print("-"*40)

    for depth in depths:
        result = bench.benchmark_serial_composition(depth)
        per_op_kb = (result.peak_memory_mb * 1024) / depth
        print(f"{depth:<10} {result.peak_memory_mb:<15.2f} {per_op_kb:<15.2f}")

    print("\nParallel Composition Memory Growth:")
    print(f"{'Channels':<10} {'Memory (MB)':<15} {'Per-Channel (KB)':<15}")
    print("-"*40)

    for width in depths:
        result = bench.benchmark_recursive_parallel(width)
        per_ch_kb = (result.peak_memory_mb * 1024) / width
        print(f"{width:<10} {result.peak_memory_mb:<15.2f} {per_ch_kb:<15.2f}")


def main():
    """Run all performance benchmarks."""
    print("="*70)
    print("CatSeq Dialect Performance Benchmark Suite")
    print("="*70)
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    print("="*70)

    try:
        # 1. Scalability test
        run_scalability_test()

        # 2. Pattern comparison
        run_comparison_benchmarks()

        # 3. Memory profiling
        run_memory_profiling()

        # 4. Extreme stress test (optional, comment out if too slow)
        print("\n\nWARNING: Extreme stress test may take several minutes...")
        response = input("Run extreme stress test? (y/n): ").lower()
        if response == 'y':
            run_extreme_stress_test()
        else:
            print("Skipping extreme stress test.")

        print("\n" + "="*70)
        print("BENCHMARK COMPLETE")
        print("="*70)

    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user.")
    except Exception as e:
        print(f"\n\nBenchmark failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
