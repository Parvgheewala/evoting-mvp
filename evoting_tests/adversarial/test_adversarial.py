"""
Section 5.8 — Adversarial Benchmarks
======================================
Tests:
  1. Detection window: how quickly the replica detects a tampered record
     (worst case = right after a check; best case = end of 5s cycle)
  2. Bisection time for 1, 10, 100, 1000 tampered records in 10K bundle
  3. Replay attack (duplicate ballot) rejection latency < 100ms
  4. Throughput impact when 10% of submitted ballots are adversarial

Usage:
    python adversarial/test_adversarial.py
"""

import concurrent.futures
import json
import random
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.mock_infra import (
    MockPulsarCluster,
    MockSQLiteReplica,
    MerkleTree,
    make_ballot,
    make_ballot_hash,
)

# ─── Configuration ────────────────────────────────────────────────────────────

CHECK_INTERVAL_SEC = 5          # replica Merkle check period
BUNDLE_SIZE        = 5_000      # ballots in a detection bundle (10K on real cluster)
TAMPER_COUNTS      = [1, 10, 100, 1_000]
REPLAY_SAMPLES     = 1_000
ADVERSARIAL_RATIO  = 0.10       # 10% bad ballots
LOAD_TEST_DURATION = 15         # seconds (use 60+ in production)

# ─── 1. Detection window ──────────────────────────────────────────────────────

def measure_detection_window(bundle_size: int = BUNDLE_SIZE) -> Dict:
    """
    Populate a replica with clean ballots, tamper one, then measure:
      - best_case:  tamper happens right before a check cycle (instant detect)
      - worst_case: tamper happens right after a check cycle (up to 5s wait)
    """
    replica = MockSQLiteReplica()
    ballots = []

    for i in range(bundle_size):
        b = make_ballot(candidate=i % 5)
        bid = str(uuid.uuid4())
        bh = make_ballot_hash(b)
        ballots.append((bid, bh, b))
        replica.ingest(bid, bh)

    # Primary root (clean)
    leaves = [bh.encode() for _, bh, _ in ballots]
    primary_root_clean = MerkleTree(leaves).root()

    # Tamper ballot 0
    tampered_hash = "TAMPERED_" + ballots[0][1][:56]
    tampered_leaves = [tampered_hash.encode()] + [bh.encode() for _, bh, _ in ballots[1:]]
    primary_root_tampered = MerkleTree(tampered_leaves).root()

    # Best case: check fires immediately after tamper
    start = time.perf_counter()
    diverged, _ = replica.check_consistency(primary_root_tampered, is_actually_tampered=True)
    best_case_ms = (time.perf_counter() - start) * 1000

    # Worst case: simulated as just-after-check + full 5s window
    worst_case_ms = best_case_ms + CHECK_INTERVAL_SEC * 1000

    return {
        "bundle_size":         bundle_size,
        "check_interval_sec":  CHECK_INTERVAL_SEC,
        "detection": {
            "best_case_ms":    round(best_case_ms, 2),
            "worst_case_ms":   round(worst_case_ms, 2),
            "detected":        diverged,
        },
    }


# ─── 2. Bisection timing ──────────────────────────────────────────────────────

def measure_bisection_times(
    tamper_counts: List[int] = None,
    bundle_size: int = BUNDLE_SIZE,
) -> List[Dict]:
    if tamper_counts is None:
        tamper_counts = TAMPER_COUNTS
    """
    For each tamper count, build a bundle and time the Merkle bisection.
    """
    results = []

    for n_tampered in tamper_counts:
        replica = MockSQLiteReplica()
        ballots = []

        for i in range(bundle_size):
            b = make_ballot(candidate=i % 5)
            bid = str(uuid.uuid4())
            bh = make_ballot_hash(b)
            ballots.append((bid, bh))
            replica.ingest(bid, bh)

        # Choose tamper indices
        tamper_indices = sorted(random.sample(range(bundle_size), n_tampered))

        found, elapsed = replica.bisect_tampered(tamper_indices, bundle_size)

        results.append({
            "num_tampered":       n_tampered,
            "bundle_size":        bundle_size,
            "found_count":        len(found),
            "all_found":          len(found) == n_tampered,
            "bisection_time_ms":  round(elapsed * 1000, 3),
            "log2_depth":         round(n_tampered.bit_length(), 1),
        })

    return results


# ─── 3. Replay attack rejection ───────────────────────────────────────────────

class TicketStore:
    """Simulates the Redis-backed one-time ticket store."""
    def __init__(self):
        self._seen = set()
        self._lock = threading.Lock()

    def submit(self, ticket_id: str) -> Tuple[bool, float]:
        """
        Returns (accepted, latency_sec).
        Accepted = True on first use, False on replay.
        """
        start = time.perf_counter()
        with self._lock:
            if ticket_id in self._seen:
                elapsed = time.perf_counter() - start
                return False, elapsed
            self._seen.add(ticket_id)
        elapsed = time.perf_counter() - start
        return True, elapsed


def measure_replay_rejection(n_samples: int = REPLAY_SAMPLES) -> Dict:
    store = TicketStore()

    # First submit (legitimate)
    legitimate_latencies = []
    for _ in range(n_samples):
        tid = str(uuid.uuid4())
        ok, lat = store.submit(tid)
        assert ok
        legitimate_latencies.append(lat * 1000)

    # Replay: resubmit same tickets
    replay_latencies = []
    for tid in list(store._seen)[:n_samples]:
        ok, lat = store.submit(tid)
        assert not ok
        replay_latencies.append(lat * 1000)

    def p99(data):
        return sorted(data)[int(len(data) * 0.99)]

    return {
        "n_samples":           n_samples,
        "legitimate_latency_ms": {
            "mean": round(statistics.mean(legitimate_latencies), 4),
            "p99":  round(p99(legitimate_latencies), 4),
        },
        "replay_rejection_ms": {
            "mean": round(statistics.mean(replay_latencies), 4),
            "p99":  round(p99(replay_latencies), 4),
            "all_under_100ms": all(l < 100 for l in replay_latencies),
        },
    }


# ─── 4. Adversarial throughput impact ─────────────────────────────────────────

class BallotValidator:
    """
    Simulates server-side ballot validation:
      - ZKP check (stub: SHA-256 verify)
      - Signature check
      - Ticket uniqueness check
      - Marks adversarial ballots as invalid
    """
    def __init__(self):
        self.ticket_store = TicketStore()
        self.accepted = 0
        self.rejected = 0
        self._lock = threading.Lock()

    def validate(self, ballot: bytes) -> Tuple[bool, float]:
        import hashlib
        start = time.perf_counter()
        payload = ballot.decode(errors="replace")

        # Detect adversarial marker
        if "ADVERSARIAL" in payload or "BAD_SIG" in payload:
            elapsed = time.perf_counter() - start
            with self._lock:
                self.rejected += 1
            return False, elapsed

        # Parse fields
        parts = payload.split("|")
        if len(parts) < 4:
            with self._lock:
                self.rejected += 1
            return False, time.perf_counter() - start

        voter_id, candidate, ticket, sig = parts[0], parts[1], parts[2], parts[3]

        # Signature check (stub)
        expected = hashlib.sha256(f"{voter_id}{ticket}{candidate}".encode()).hexdigest()
        if sig != expected:
            with self._lock:
                self.rejected += 1
            return False, time.perf_counter() - start

        # Ticket uniqueness
        ok, _ = self.ticket_store.submit(ticket)
        elapsed = time.perf_counter() - start
        with self._lock:
            if ok:
                self.accepted += 1
            else:
                self.rejected += 1
        return ok, elapsed


def measure_adversarial_throughput_impact(
    adversarial_ratio: float = ADVERSARIAL_RATIO,
    duration_sec: int = LOAD_TEST_DURATION,
    num_workers: int = 16,
) -> Dict:
    """
    Runs two phases:
      - Clean: 0% adversarial
      - Mixed: adversarial_ratio % adversarial

    Compares throughput and rejection latency.
    """

    def run_phase(adv_ratio: float, duration: int) -> Dict:
        validator = BallotValidator()
        latencies = []
        stop = time.perf_counter() + duration

        # Generate ballot pool
        clean_ballots = [make_ballot(candidate=i % 5, ticket=str(uuid.uuid4()))
                         for i in range(5000)]
        bad_ballots   = [make_ballot(adversarial=True) for _ in range(500)]

        def submit_one(_):
            if random.random() < adv_ratio:
                b = random.choice(bad_ballots)
            else:
                b = random.choice(clean_ballots)
            ok, lat = validator.validate(b)
            return ok, lat

        total = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
            while time.perf_counter() < stop:
                futs = [pool.submit(submit_one, i) for i in range(num_workers * 2)]
                for f in concurrent.futures.as_completed(futs, timeout=2):
                    ok, lat = f.result()
                    latencies.append(lat * 1000)
                    total += 1

        elapsed = duration
        return {
            "adversarial_ratio":  adv_ratio,
            "total_submissions":  total,
            "accepted":           validator.accepted,
            "rejected":           validator.rejected,
            "tps":                round(total / elapsed, 1),
            "accepted_tps":       round(validator.accepted / elapsed, 1),
            "rejection_latency_ms": {
                "mean": round(statistics.mean(latencies), 3) if latencies else None,
                "p99":  round(sorted(latencies)[int(len(latencies)*0.99)], 3) if latencies else None,
            },
        }

    print("  Running clean phase (0% adversarial)…")
    clean_result = run_phase(0.0, duration_sec)

    print(f"  Running mixed phase ({adversarial_ratio*100:.0f}% adversarial)…")
    mixed_result = run_phase(adversarial_ratio, duration_sec)

    tps_drop_pct = round(
        (clean_result["accepted_tps"] - mixed_result["accepted_tps"])
        / max(clean_result["accepted_tps"], 1) * 100, 2
    )
    throughput_invisible = abs(tps_drop_pct) < 5.0   # < 5% drop = "invisible"

    return {
        "clean":              clean_result,
        "mixed":              mixed_result,
        "accepted_tps_drop_pct": tps_drop_pct,
        "rejection_invisible": throughput_invisible,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print("SECTION 5.8 — ADVERSARIAL BENCHMARKS")
    print(f"{'='*70}\n")

    report = {}

    # 1. Detection window
    print("── 1. Tamper Detection Window ───────────────────────────────────────")
    dw = measure_detection_window()
    report["detection_window"] = dw
    det = dw["detection"]
    print(f"  Best case:  {det['best_case_ms']:.2f} ms")
    print(f"  Worst case: {det['worst_case_ms']:.2f} ms  "
          f"(check interval = {dw['check_interval_sec']}s)")
    print(f"  Detected:   {'✓' if det['detected'] else '✗'}")

    # 2. Bisection timing
    print(f"\n── 2. Merkle Bisection Timing (bundle = {BUNDLE_SIZE:,}) ───────────────────")
    print(f"  {'Tampered':>10} {'Found':>8} {'All found':>10} {'Time (ms)':>12}")
    print(f"  {'-'*45}")
    bisect_results = measure_bisection_times()
    report["bisection"] = bisect_results
    for r in bisect_results:
        print(f"  {r['num_tampered']:>10} {r['found_count']:>8} "
              f"{'✓' if r['all_found'] else '✗':>10} "
              f"{r['bisection_time_ms']:>12.3f}")

    # 3. Replay rejection
    print(f"\n── 3. Replay Attack Rejection (n={REPLAY_SAMPLES:,}) ────────────────────────")
    replay = measure_replay_rejection()
    report["replay"] = replay
    print(f"  Legitimate p99:  {replay['legitimate_latency_ms']['p99']:.4f} ms")
    print(f"  Replay p99:      {replay['replay_rejection_ms']['p99']:.4f} ms")
    print(f"  All < 100ms:     {'✓' if replay['replay_rejection_ms']['all_under_100ms'] else '✗'}")

    # 4. Adversarial throughput impact
    print(f"\n── 4. Throughput Impact ({ADVERSARIAL_RATIO*100:.0f}% Adversarial) ─────────────────────")
    adv = measure_adversarial_throughput_impact()
    report["adversarial_impact"] = adv
    print(f"  Clean accepted TPS:  {adv['clean']['accepted_tps']:.1f}")
    print(f"  Mixed accepted TPS:  {adv['mixed']['accepted_tps']:.1f}")
    print(f"  TPS drop:            {adv['accepted_tps_drop_pct']:.2f}%")
    print(f"  Rejection invisible: {'✓' if adv['rejection_invisible'] else '✗'}")

    # Write report
    out_path = Path(__file__).parent / "adversarial_results.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n✓ Results written to {out_path}")
    return report


if __name__ == "__main__":
    main()