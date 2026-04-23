"""
run_all_benchmarks.py
=====================
Master runner for all e-voting benchmark sections.
Produces a unified JSON report with predicted vs. required values.

Usage:
    python run_all_benchmarks.py              # quick (60s runs)
    python run_all_benchmarks.py --full       # full (600s runs)
    python run_all_benchmarks.py --section 5.4 5.6   # specific sections
"""

import argparse
import json
import sys
import time
from pathlib import Path

# ─── Section registry ─────────────────────────────────────────────────────────

SECTIONS = {
    "5.4": ("Scalability Curve",        "scalability.test_scalability_curve"),
    "5.5": ("Fault Tolerance",          "fault_tolerance.test_fault_tolerance"),
    "5.6": ("ZKP Overhead",             "zkp_overhead.test_zkp_overhead"),
    "5.7": ("Homomorphic Tally",        "homomorphic_tally.test_homomorphic_tally"),
    "5.8": ("Adversarial Benchmarks",   "adversarial.test_adversarial"),
    "5.2": ("500K TPS Stress Test",     "stress_test.test_500k_tps"),
}

# Pass/fail thresholds (from the spec)
THRESHOLDS = {
    "target_tps":                500_000,
    "replica_check_sec":         5,
    "replay_rejection_ms":       100,
    "fault_wall_tps_drop_pct":   30,    # allow up to 30% TPS drop on 1 node kill
    "bisection_1000_ms":         1000,  # bisect 1000 tampered in <1 second
}


def run_section(module_path: str, full: bool) -> dict:
    """Dynamically import and run a section's main() function."""
    import importlib
    root = str(Path(__file__).parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    mod = importlib.import_module(module_path)
    if full and hasattr(mod, "main") and "full_run" in mod.main.__code__.co_varnames:
        return mod.main(full_run=True)
    return mod.main()


def evaluate_results(section_id: str, result: dict) -> list:
    """Return a list of (check_name, passed, detail) tuples."""
    checks = []

    if section_id == "5.4":
        # Check that 16-node predicted TPS reaches 500K for target rate
        for r in result:
            if r.get("num_nodes") == 16 and r.get("rate") == "target":
                passed = not r.get("wall_hit", True)
                checks.append((
                    "16-node 500K TPS target",
                    passed,
                    f"predicted {r.get('predicted_real_tps', 0):,.0f} TPS"
                ))
            if r.get("replica_within_5sec") is False:
                checks.append((
                    f"Replica check ≤5s at {r.get('num_nodes')} nodes",
                    False,
                    f"latency {r.get('replica_verification_latency_sec')}s"
                ))

    elif section_id == "5.5":
        for p in result.get("phases", []):
            if "killing_node_2" in p.get("label", ""):
                drop = p.get("dropped_no_quorum", 0)
                checks.append((
                    "Quorum failure: writes dropped (not silently lost)",
                    drop > 0 or p.get("failures", 0) > 0,
                    f"dropped={drop}"
                ))
        fp = result.get("merkle", {}).get("false_positives", 0)
        checks.append(("No Merkle false positives during node failure", fp == 0, f"fp={fp}"))

    elif section_id == "5.6":
        replay = None
        for r in result.get("verification", []):
            if r.get("scheme") == "schnorr":
                replay = r
        if replay:
            ok = replay["verify_time_ms"]["mean"] < 10  # <10ms per verify
            checks.append(("Schnorr verify <10ms mean", ok,
                            f"{replay['verify_time_ms']['mean']}ms"))
        conc = result.get("concurrency", [])
        if conc:
            contended = any(r["contention_detected"] for r in conc)
            checks.append(("No lock contention up to 32 workers", not contended,
                            "contention detected" if contended else "linear scaling"))

    elif section_id == "5.7":
        for r in result.get("sequential", []):
            if r.get("num_ballots") == 100_000_000:
                fits_ram = r.get("memory_mb", 0) < 60_000
                checks.append(("100M ballots fit in 60 GB RAM", fits_ram,
                                f"{r.get('memory_mb', 0):.0f} MB"))

    elif section_id == "5.8":
        rr = result.get("replay", {}).get("replay_rejection_ms", {})
        checks.append((
            "Replay rejection p99 < 100ms",
            rr.get("all_under_100ms", False),
            f"p99={rr.get('p99')}ms"
        ))
        adv = result.get("adversarial_impact", {})
        checks.append((
            "10% adversarial load invisible (< 5% TPS drop)",
            adv.get("rejection_invisible", False),
            f"drop={adv.get('accepted_tps_drop_pct')}%"
        ))

    elif section_id == "5.2":
        tp = result.get("throughput", {})
        checks.append((
            "500K TPS target achieved (16 nodes)",
            tp.get("target_achieved", False),
            f"sustained {tp.get('sustained_real_tps', 0):,.0f} TPS"
        ))
        lat = result.get("latency_ms", {})
        if lat.get("p99"):
            checks.append(("p99 latency <500ms", lat["p99"] < 500, f"{lat['p99']}ms"))

    return checks


def print_summary(all_checks: dict):
    print(f"\n{'='*70}")
    print("BENCHMARK SUMMARY — PASS / FAIL")
    print(f"{'='*70}")
    total_pass = total_fail = 0
    for section_id, checks in all_checks.items():
        name = SECTIONS[section_id][0]
        print(f"\nSection {section_id} — {name}")
        for check, passed, detail in checks:
            symbol = "✓" if passed else "✗"
            status = "PASS" if passed else "FAIL"
            print(f"  {symbol} [{status}] {check}")
            print(f"         → {detail}")
            if passed:
                total_pass += 1
            else:
                total_fail += 1
    print(f"\n{'─'*70}")
    print(f"  Total:  {total_pass + total_fail} checks | "
          f"{total_pass} PASS | {total_fail} FAIL")
    if total_fail == 0:
        print("  🎉 All benchmarks passed — Q1 sign-off criteria met")
    else:
        print(f"  ⚠  {total_fail} benchmark(s) need attention before Q1")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="E-Voting Benchmark Runner")
    parser.add_argument("--full", action="store_true",
                        help="Run full 10-minute benchmarks (default: 60s)")
    parser.add_argument("--section", nargs="+",
                        help="Run specific sections e.g. --section 5.4 5.6")
    args = parser.parse_args()

    sections_to_run = args.section or list(SECTIONS.keys())
    unknown = [s for s in sections_to_run if s not in SECTIONS]
    if unknown:
        print(f"Unknown sections: {unknown}. Valid: {list(SECTIONS.keys())}")
        sys.exit(1)

    print(f"\n{'='*70}")
    print("E-VOTING BENCHMARK SUITE — MASTER RUNNER")
    print(f"Sections: {sections_to_run} | Mode: {'full (600s)' if args.full else 'quick (60s)'}")
    print(f"{'='*70}\n")

    master_report = {"run_ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sections": {}}
    all_checks: dict = {}

    for section_id in sections_to_run:
        name, module_path = SECTIONS[section_id]
        print(f"\n{'─'*70}")
        print(f"Running Section {section_id}: {name}")
        print(f"{'─'*70}")

        try:
            t0 = time.perf_counter()
            result = run_section(module_path, args.full)
            elapsed = time.perf_counter() - t0
            checks = evaluate_results(section_id, result)
            all_checks[section_id] = checks
            master_report["sections"][section_id] = {
                "name":        name,
                "elapsed_sec": round(elapsed, 2),
                "result":      result,
                "checks":      [(c, p, d) for c, p, d in checks],
            }
            print(f"\n  ✓ Section {section_id} complete in {elapsed:.1f}s")
        except Exception as e:
            print(f"\n  ✗ Section {section_id} FAILED: {e}")
            import traceback
            traceback.print_exc()
            all_checks[section_id] = [(f"Section {section_id} crashed", False, str(e))]

    print_summary(all_checks)

    out_path = Path(__file__).parent / "master_benchmark_report.json"
    with open(out_path, "w") as f:
        json.dump(master_report, f, indent=2)
    print(f"Full report written to {out_path}\n")


if __name__ == "__main__":
    main()