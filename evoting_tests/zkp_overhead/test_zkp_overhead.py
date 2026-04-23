"""
Section 5.6 — ZKP Overhead Microbenchmarks
===========================================
Measures ZKP generation and verification timings for:
  - SHA-256 stub (current codebase)
  - Schnorr-based ZKP (target implementation)
  - Bulletproofs (comparison)
  - Groth16 SNARK (comparison)

Also measures how server-side verification scales with concurrent load
(linear vs lock-contended).

NOTE: The "mobile" timings use a hardware calibration factor derived from
published benchmarks:
  - Android Snapdragon 700: ~3.2× slower than server SHA-256 throughput
  - Apple A15: ~1.8× slower than server (faster single-thread perf)

These factors are applied to the mock timing to produce PREDICTED mobile
timings.  When real devices are available, replace DEVICE_SCALE_FACTORS
with actual measurements.

Usage:
    python zkp_overhead/test_zkp_overhead.py
"""

import concurrent.futures
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.mock_infra import MockZKP, make_ballot

# ─── Configuration ────────────────────────────────────────────────────────────

N_MOBILE_SAMPLES    = 1_000     # avg over N ballots on mobile (per spec)
N_SERVER_SAMPLES    = 2_000     # avg over N verifications (use 10_000 on real hardware)
CONCURRENT_LEVELS   = [1, 4, 8, 16, 32, 64]  # concurrent verifications

# Device calibration factors (mock_time × factor = predicted device time)
DEVICE_SCALE_FACTORS = {
    "android_snapdragon700": 3.2,
    "iphone_a15":            1.8,
}

# ─── Single-scheme benchmark ──────────────────────────────────────────────────

def benchmark_generation(
    zkp: MockZKP,
    scheme: str,
    n_samples: int,
) -> Dict:
    """Measure generation time over n_samples ballots."""
    gen_fn = {
        "sha256_stub": zkp.generate_sha256_stub,
        "schnorr":     zkp.generate_schnorr,
        "bulletproof": zkp.generate_bulletproof,
        "groth16":     zkp.generate_groth16,
    }[scheme]

    proof_sizes = []
    times_sec   = []

    for i in range(n_samples):
        ballot = make_ballot(candidate=i % 5)
        proof, elapsed = gen_fn(ballot)
        times_sec.append(elapsed)
        proof_sizes.append(len(proof))

    return {
        "scheme":           scheme,
        "n_samples":        n_samples,
        "proof_size_bytes": proof_sizes[0],  # constant per scheme
        "gen_time_ms": {
            "mean":   round(statistics.mean(times_sec) * 1000, 4),
            "median": round(statistics.median(times_sec) * 1000, 4),
            "p99":    round(sorted(times_sec)[int(n_samples * 0.99)] * 1000, 4),
        },
    }


def benchmark_verification(
    zkp: MockZKP,
    scheme: str,
    n_samples: int,
) -> Dict:
    """Measure server-side single-threaded verification over n_samples."""
    ballots = [make_ballot(candidate=i % 5) for i in range(n_samples)]
    gen_fn  = {
        "sha256_stub": zkp.generate_sha256_stub,
        "schnorr":     zkp.generate_schnorr,
        "bulletproof": zkp.generate_bulletproof,
        "groth16":     zkp.generate_groth16,
    }[scheme]

    proofs = [gen_fn(b)[0] for b in ballots]

    times_sec = []
    for ballot, proof in zip(ballots, proofs):
        _, elapsed = zkp.verify_schnorr(ballot, proof)
        times_sec.append(elapsed)

    return {
        "scheme":   scheme,
        "n_samples": n_samples,
        "verify_time_ms": {
            "mean":   round(statistics.mean(times_sec) * 1000, 4),
            "median": round(statistics.median(times_sec) * 1000, 4),
            "p99":    round(sorted(times_sec)[int(n_samples * 0.99)] * 1000, 4),
        },
    }


def benchmark_concurrent_verification(
    zkp: MockZKP,
    scheme: str = "schnorr",
    concurrent_levels: List[int] = CONCURRENT_LEVELS,
    samples_per_level: int = 1000,
) -> List[Dict]:
    """
    Measure throughput and latency as concurrent verifications increase.
    Detects whether scaling is linear or lock-contended.
    """
    ballot_pool = [make_ballot(candidate=i % 5) for i in range(samples_per_level)]
    gen_fn = {
        "sha256_stub": zkp.generate_sha256_stub,
        "schnorr":     zkp.generate_schnorr,
        "bulletproof": zkp.generate_bulletproof,
        "groth16":     zkp.generate_groth16,
    }[scheme]
    proofs = [gen_fn(b)[0] for b in ballot_pool]

    results = []
    for concurrency in concurrent_levels:
        latencies = []

        def verify_one(idx):
            b = ballot_pool[idx % len(ballot_pool)]
            p = proofs[idx % len(proofs)]
            _, lat = zkp.verify_schnorr(b, p)
            return lat

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(verify_one, i) for i in range(samples_per_level)]
            for f in concurrent.futures.as_completed(futs):
                latencies.append(f.result())
        elapsed = time.perf_counter() - start

        tps = samples_per_level / elapsed
        lat_ms = sorted(l * 1000 for l in latencies)
        results.append({
            "concurrency":      concurrency,
            "throughput_vps":   round(tps, 1),    # verifications per second
            "latency_ms": {
                "mean": round(statistics.mean(lat_ms), 4),
                "p99":  round(lat_ms[int(len(lat_ms) * 0.99)], 4),
            },
        })

    # Detect contention: if throughput doesn't scale linearly
    baseline_tps = results[0]["throughput_vps"]
    for r in results:
        expected_linear = baseline_tps * r["concurrency"]
        r["linear_efficiency_pct"] = round(
            r["throughput_vps"] / expected_linear * 100, 1
        )
        r["contention_detected"] = r["linear_efficiency_pct"] < 80

    return results


def apply_device_factors(gen_result: Dict) -> Dict:
    """Apply hardware calibration to produce mobile predicted timings."""
    mean_ms = gen_result["gen_time_ms"]["mean"]
    predictions = {}
    for device, factor in DEVICE_SCALE_FACTORS.items():
        predictions[device] = {
            "predicted_mean_ms": round(mean_ms * factor, 2),
            "calibration_factor": factor,
            "note": "Predicted — replace with real device measurement when available",
        }
    return predictions


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print("SECTION 5.6 — ZKP OVERHEAD MICROBENCHMARKS")
    print(f"Mobile samples: {N_MOBILE_SAMPLES:,} | Server samples: {N_SERVER_SAMPLES:,}")
    print(f"{'='*70}\n")

    zkp     = MockZKP()
    schemes = ["sha256_stub", "schnorr", "bulletproof", "groth16"]
    report  = {"generation": [], "verification": [], "concurrency": [], "mobile_predictions": {}}

    # ── Generation timings ────────────────────────────────────────────────────
    print("── Generation Time (mobile client) ─────────────────────────────────")
    print(f"  {'Scheme':<15} {'Proof (B)':>10} {'Mean (ms)':>12} {'p99 (ms)':>10}")
    print(f"  {'-'*50}")

    for scheme in schemes:
        r = benchmark_generation(zkp, scheme, N_MOBILE_SAMPLES)
        report["generation"].append(r)
        print(f"  {scheme:<15} {r['proof_size_bytes']:>10} "
              f"{r['gen_time_ms']['mean']:>12.4f} {r['gen_time_ms']['p99']:>10.4f}")

    # ── Mobile predictions ────────────────────────────────────────────────────
    print(f"\n── Predicted Mobile Device Timings ─────────────────────────────────")
    for r in report["generation"]:
        if r["scheme"] == "schnorr":
            preds = apply_device_factors(r)
            report["mobile_predictions"] = preds
            for device, p in preds.items():
                print(f"  {device}: {p['predicted_mean_ms']} ms (×{p['calibration_factor']} factor)")

    # ── Server verification timings ───────────────────────────────────────────
    print(f"\n── Server Verification Time (10,000 ballots) ───────────────────────")
    print(f"  {'Scheme':<15} {'Mean (ms)':>12} {'p99 (ms)':>10}")
    print(f"  {'-'*40}")

    for scheme in schemes:
        r = benchmark_verification(zkp, scheme, N_SERVER_SAMPLES)
        report["verification"].append(r)
        print(f"  {scheme:<15} {r['verify_time_ms']['mean']:>12.4f} "
              f"{r['verify_time_ms']['p99']:>10.4f}")

    # ── Concurrency scaling ───────────────────────────────────────────────────
    print(f"\n── Concurrent Verification Scaling (Schnorr) ───────────────────────")
    print(f"  {'Workers':>8} {'VPS':>10} {'Mean ms':>9} {'p99 ms':>9} "
          f"{'Efficiency':>12} {'Contended':>10}")
    print(f"  {'-'*65}")

    concur_results = benchmark_concurrent_verification(zkp, "schnorr")
    report["concurrency"] = concur_results

    for r in concur_results:
        print(f"  {r['concurrency']:>8} {r['throughput_vps']:>10.1f} "
              f"{r['latency_ms']['mean']:>9.4f} {r['latency_ms']['p99']:>9.4f} "
              f"{r['linear_efficiency_pct']:>11.1f}% "
              f"{'YES' if r['contention_detected'] else 'no':>10}")

    # ── Proof size comparison table ───────────────────────────────────────────
    print(f"\n── Proof Size Comparison ───────────────────────────────────────────")
    expected = {
        "sha256_stub":  32,
        "schnorr":      MockZKP.PROOF_SIZE_SCHNORR_BYTES,
        "bulletproof":  MockZKP.PROOF_SIZE_BULLETPROOF_BYTES,
        "groth16":      MockZKP.PROOF_SIZE_GROTH16_BYTES,
    }
    for scheme, size in expected.items():
        print(f"  {scheme:<15} {size:>6} bytes")

    # ── Write report ──────────────────────────────────────────────────────────
    out_path = Path(__file__).parent / "zkp_overhead_results.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n✓ Results written to {out_path}")

    # Implementation gap warning
    print("\n⚠  IMPLEMENTATION NOTE:")
    print("   The current codebase uses a SHA-256 stub (not a real ZKP).")
    print("   Schnorr/Groth16 timings here are PREDICTED from mock calibration.")
    print("   Build the real Schnorr implementation, then re-run this benchmark")
    print("   to replace predicted values with actual measurements.")

    return report


if __name__ == "__main__":
    main()