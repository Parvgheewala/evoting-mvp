"""
Section 5.7 — Homomorphic Tallying Overhead
============================================
Times Paillier accumulation at:
  100K, 1M, 10M, 100M ballots × 5 candidates

Also measures:
  - Threshold decryption ceremony (3-of-5 trustees)
  - Whether accumulation is parallelized across candidates
  - Memory usage at each ballot count

NOTE: The current codebase uses SQL COUNT GROUP BY, not Paillier.
      These timings simulate the REAL Paillier cost using calibrated mocks.
      Replace with actual measurements once paillier-python / gmpy2 is wired.

Usage:
    python homomorphic_tally/test_homomorphic_tally.py
"""

import json
import multiprocessing
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.mock_infra import MockPaillier

# ─── Configuration ────────────────────────────────────────────────────────────

BALLOT_COUNTS   = [100_000, 1_000_000, 10_000_000]   # add 100_000_000 for full run
NUM_CANDIDATES  = 5
NUM_TRUSTEES    = 5
THRESHOLD       = 3
SCALE_FACTOR    = 1.0   # Mock Paillier is already calibrated to real timing

# ─── Sequential accumulation ─────────────────────────────────────────────────

def run_sequential(paillier: MockPaillier, num_ballots: int) -> Dict:
    """Single-threaded accumulation across all candidates combined."""
    start = time.perf_counter()
    elapsed, mem_mb = paillier.accumulate(num_ballots, NUM_CANDIDATES)
    wall_time = time.perf_counter() - start

    return {
        "mode":            "sequential",
        "num_ballots":     num_ballots,
        "elapsed_sec":     round(elapsed, 4),
        "wall_sec":        round(wall_time, 4),
        "memory_mb":       round(mem_mb, 2),
        "tally_rate_kbps": round(num_ballots / max(elapsed, 0.001) / 1000, 1),
    }


def _accumulate_candidate(args) -> Tuple[int, float, float]:
    """Worker: accumulate one candidate's slice of ballots."""
    candidate, num_ballots, num_candidates = args
    paillier = MockPaillier()
    ballots_for_candidate = num_ballots // num_candidates
    elapsed, mem = paillier.accumulate(ballots_for_candidate, 1)
    return candidate, elapsed, mem


def run_parallel(num_ballots: int) -> Dict:
    """Parallel accumulation — one process per candidate."""
    worker_args = [
        (c, num_ballots, NUM_CANDIDATES) for c in range(NUM_CANDIDATES)
    ]

    start = time.perf_counter()
    with multiprocessing.Pool(processes=NUM_CANDIDATES) as pool:
        results = pool.map(_accumulate_candidate, worker_args)
    wall_time = time.perf_counter() - start

    max_elapsed  = max(r[1] for r in results)
    total_mem_mb = sum(r[2] for r in results)

    return {
        "mode":            "parallel",
        "num_ballots":     num_ballots,
        "num_candidates":  NUM_CANDIDATES,
        "wall_sec":        round(wall_time, 4),
        "bottleneck_sec":  round(max_elapsed, 4),
        "memory_mb":       round(total_mem_mb, 2),
        "per_candidate_sec": {
            f"candidate_{r[0]}": round(r[1], 4) for r in results
        },
    }


def compute_speedup(seq: Dict, par: Dict) -> float:
    """Amdahl speedup of parallel over sequential."""
    if par["wall_sec"] == 0:
        return float("inf")
    return round(seq["wall_sec"] / par["wall_sec"], 2)


# ─── Threshold decryption ─────────────────────────────────────────────────────

def run_threshold_decryption(paillier: MockPaillier) -> Dict:
    start = time.perf_counter()
    elapsed = paillier.threshold_decrypt(
        num_trustees=NUM_TRUSTEES, threshold=THRESHOLD
    )
    wall = time.perf_counter() - start
    return {
        "trustees":    NUM_TRUSTEES,
        "threshold":   THRESHOLD,
        "elapsed_sec": round(elapsed, 6),
        "wall_sec":    round(wall, 6),
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print("SECTION 5.7 — HOMOMORPHIC TALLYING OVERHEAD")
    print(f"Candidates: {NUM_CANDIDATES} | Trustees: {THRESHOLD}/{NUM_TRUSTEES}")
    print(f"{'='*70}\n")

    paillier = MockPaillier()
    report   = {"sequential": [], "parallel": [], "speedups": [], "decryption": None}

    # ── Sequential ────────────────────────────────────────────────────────────
    print("── Sequential Accumulation ─────────────────────────────────────────")
    print(f"  {'Ballots':>12} {'Elapsed (s)':>13} {'Mem (MB)':>10} {'Rate (K/s)':>12}")
    print(f"  {'-'*52}")

    seq_results = {}
    for n in BALLOT_COUNTS:
        r = run_sequential(paillier, n)
        report["sequential"].append(r)
        seq_results[n] = r
        print(f"  {n:>12,} {r['elapsed_sec']:>13.4f} {r['memory_mb']:>10.1f} "
              f"{r['tally_rate_kbps']:>12.1f}")

    # ── Parallel (per-candidate) ───────────────────────────────────────────────
    print(f"\n── Parallel Accumulation ({NUM_CANDIDATES} candidates × 1 process) ──────────────")
    print(f"  {'Ballots':>12} {'Wall (s)':>10} {'Mem (MB)':>10} {'Speedup':>9}")
    print(f"  {'-'*46}")

    for n in BALLOT_COUNTS:
        r = run_parallel(n)
        report["parallel"].append(r)
        speedup = compute_speedup(seq_results[n], r)
        report["speedups"].append({"num_ballots": n, "speedup": speedup})
        print(f"  {n:>12,} {r['wall_sec']:>10.4f} {r['memory_mb']:>10.1f} "
              f"{speedup:>9.2f}×")

    # ── Threshold decryption ──────────────────────────────────────────────────
    print(f"\n── Threshold Decryption Ceremony ({THRESHOLD}-of-{NUM_TRUSTEES}) ────────────────────")
    dec = run_threshold_decryption(paillier)
    report["decryption"] = dec
    print(f"  Elapsed: {dec['elapsed_sec']*1000:.2f} ms")

    # ── Memory analysis ───────────────────────────────────────────────────────
    print(f"\n── Memory Usage Analysis ───────────────────────────────────────────")
    print(f"  Paillier 2048-bit ciphertext size: {MockPaillier.CIPHERTEXT_SIZE_BYTES} bytes")
    for r in report["sequential"]:
        print(f"  {r['num_ballots']:>12,} ballots → {r['memory_mb']:>8.1f} MB in RAM")

    # ── Feasibility note (extrapolate 100M from 10M) ──────────────────────────
    print(f"\n── 100M Ballot Feasibility (extrapolated) ──────────────────────────")
    r10m = next(r for r in report["sequential"] if r["num_ballots"] == 10_000_000)
    rate_kbps = r10m["tally_rate_kbps"]
    est_elapsed = 100_000_000 / (rate_kbps * 1000)
    est_mem_mb  = 100_000_000 * MockPaillier.CIPHERTEXT_SIZE_BYTES / (1024 * 1024)
    print(f"  Sequential (extrapolated): {est_elapsed:.1f}s | Memory: {est_mem_mb:.0f} MB")
    if est_mem_mb > 50_000:
        print("  ⚠  Memory > 50 GB — streaming accumulation required for 100M ballots")
    else:
        print("  ✓  Fits in RAM")

    # ── Write report ──────────────────────────────────────────────────────────
    out_path = Path(__file__).parent / "homomorphic_tally_results.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n✓ Results written to {out_path}")

    print("\n⚠  IMPLEMENTATION NOTE:")
    print("   Current tally is SQL COUNT GROUP BY — not Paillier.")
    print("   These timings are PREDICTED using calibrated mocks.")
    print("   Implement paillier-python / gmpy2 accumulation,")
    print("   then re-run to replace with real measurements.")

    return report


if __name__ == "__main__":
    main()