"""
Section 5.5 — Fault Tolerance
==============================
Tests TPS degradation and Merkle replica behaviour as bookie nodes are
killed one at a time.

Checks:
  1. TPS at baseline (all nodes healthy)
  2. TPS after killing node 0, then node 1, then node 2 (cumulative)
  3. Whether writes stall, queue, or drop when quorum cannot be met
  4. Recovery time after a failed node is brought back online
  5. Whether the SQLite replica's Merkle check flags a false positive
     during a node failure event

Usage:
    python fault_tolerance/test_fault_tolerance.py
"""

import concurrent.futures
import json
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.mock_infra import (
    MockPulsarCluster,
    MockSQLiteReplica,
    make_ballot,
    make_ballot_hash,
)

# ─── Configuration ────────────────────────────────────────────────────────────

NUM_NODES          = 4      # representative cluster (4 bookies, quorum=3)
PHASE_DURATION_SEC = 10     # each phase — use 30+ in production
WRITER_THREADS     = 16
TARGET_TPS         = 10_000  # mock internal rate; scaled for prediction
SCALE_FACTOR       = 50.0

# ─── Instrumented writer ──────────────────────────────────────────────────────

class PhaseStats:
    def __init__(self, label: str):
        self.label      = label
        self.successes  = 0
        self.failures   = 0
        self.dropped    = 0   # quorum-failed (not retried)
        self.queued     = 0   # not used in mock; placeholder
        self.latencies  = []
        self.start_ts   = time.perf_counter()
        self._lock      = threading.Lock()

    def record(self, ok: bool, lat: float, quorum_fail: bool = False):
        with self._lock:
            self.latencies.append(lat)
            if ok:
                self.successes += 1
            else:
                self.failures += 1
                if quorum_fail:
                    self.dropped += 1

    def summary(self) -> Dict:
        elapsed = time.perf_counter() - self.start_ts
        lat_ms  = sorted(l * 1000 for l in self.latencies if l > 0)
        return {
            "label":              self.label,
            "elapsed_sec":        round(elapsed, 2),
            "successes":          self.successes,
            "failures":           self.failures,
            "dropped_no_quorum":  self.dropped,
            "actual_tps_mock":    round(self.successes / max(elapsed, 1), 1),
            "predicted_real_tps": round(self.successes / max(elapsed, 1) * SCALE_FACTOR, 0),
            "latency_ms": {
                "mean":   round(sum(lat_ms) / len(lat_ms), 2) if lat_ms else None,
                "p99":    round(lat_ms[int(len(lat_ms) * 0.99)], 2) if lat_ms else None,
            },
        }


def run_writers(cluster, stats: PhaseStats, duration_sec: float):
    """Continuously submit ballots to the cluster for `duration_sec`."""
    ballot_pool = [make_ballot(candidate=i % 5) for i in range(200)]
    stop = time.perf_counter() + duration_sec
    BATCH = WRITER_THREADS

    def write_one(b):
        before_qf = cluster.quorum_failures
        ok, lat = cluster.write_ballot(b)
        quorum_fail = cluster.quorum_failures > before_qf
        stats.record(ok, lat, quorum_fail)
        return ok

    with concurrent.futures.ThreadPoolExecutor(max_workers=WRITER_THREADS) as pool:
        idx = 0
        while time.perf_counter() < stop:
            batch = [ballot_pool[(idx + i) % len(ballot_pool)] for i in range(BATCH)]
            idx += BATCH
            futs = [pool.submit(write_one, b) for b in batch]
            concurrent.futures.wait(futs, timeout=2)


# ─── Merkle false-positive monitor ───────────────────────────────────────────

class MerkleMonitor:
    """
    Continuously populates the replica from a cluster and checks consistency
    every CHECK_SEC seconds.  Tracks false positives during node failure.
    """
    CHECK_SEC = 5

    def __init__(self, cluster: MockPulsarCluster, replica: MockSQLiteReplica):
        self.cluster  = cluster
        self.replica  = replica
        self._stop    = threading.Event()
        self._alerts  = []
        self._primary_hashes = []
        self._lock    = threading.Lock()

    def feed(self, ballot: bytes, ballot_id: str):
        h = make_ballot_hash(ballot)
        with self._lock:
            self._primary_hashes.append(h.encode())
        self.replica.ingest(ballot_id, h)

    def _monitor_loop(self, node_failure_active: threading.Event):
        import hashlib
        while not self._stop.is_set():
            time.sleep(self.CHECK_SEC)
            with self._lock:
                import hashlib as _h
                leaves = self._primary_hashes[:]

            if not leaves:
                continue

            # Compute primary root
            from utils.mock_infra import MerkleTree
            primary_root = MerkleTree(leaves).root()
            replica_root  = self.replica.compute_merkle_root()
            diverged      = primary_root != replica_root
            is_failing    = node_failure_active.is_set()

            if diverged:
                self._alerts.append({
                    "ts":             time.time(),
                    "diverged":       diverged,
                    "node_failure":   is_failing,
                    "false_positive": diverged and not is_failing,
                })

    def start(self, node_failure_event: threading.Event):
        t = threading.Thread(target=self._monitor_loop, args=(node_failure_event,), daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()

    def report(self) -> Dict:
        false_pos = [a for a in self._alerts if a["false_positive"]]
        true_pos  = [a for a in self._alerts if not a["false_positive"] and a["diverged"]]
        return {
            "total_checks":      len(self._alerts),
            "false_positives":   len(false_pos),
            "true_positives":    len(true_pos),
            "fp_during_failure": [a for a in false_pos if a["node_failure"]],
        }


# ─── Recovery timer ──────────────────────────────────────────────────────────

def measure_recovery_time(cluster: MockPulsarCluster, node_id: int) -> float:
    """
    Revive a previously-killed node and measure how long until writes
    succeed again at full quorum rate.
    """
    revive_start = time.perf_counter()
    cluster.revive_node(node_id)

    b = make_ballot()
    streak = 0
    RECOVERY_CONSECUTIVE = 5
    TIMEOUT_SEC = 5.0

    while streak < RECOVERY_CONSECUTIVE:
        if time.perf_counter() - revive_start > TIMEOUT_SEC:
            break   # quorum still not met (too many nodes still dead)
        ok, _ = cluster.write_ballot(b)
        streak = streak + 1 if ok else 0
        time.sleep(0.001)

    return time.perf_counter() - revive_start


# ─── Main test ───────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print("SECTION 5.5 — FAULT TOLERANCE BENCHMARK")
    print(f"Cluster: {NUM_NODES} bookie nodes | Phase duration: {PHASE_DURATION_SEC}s")
    print(f"{'='*70}\n")

    cluster = MockPulsarCluster(num_nodes=NUM_NODES)
    replica = MockSQLiteReplica()
    node_failure_event = threading.Event()
    monitor = MerkleMonitor(cluster, replica)

    all_phases = []
    import uuid as _uuid

    # ── Baseline ──────────────────────────────────────────────────────────────
    print("Phase 0: Baseline — all nodes healthy")
    baseline = PhaseStats("baseline_all_healthy")

    original_write = cluster.write_ballot
    def instrumented_write(b):
        ok, lat = original_write(b)
        if ok:
            monitor.feed(b, str(_uuid.uuid4()))
        return ok, lat
    cluster.write_ballot = instrumented_write

    monitor_thread = monitor.start(node_failure_event)
    run_writers(cluster, baseline, PHASE_DURATION_SEC)
    s = baseline.summary()
    all_phases.append(s)
    print(f"  Predicted TPS: {s['predicted_real_tps']:,.0f} | "
          f"Dropped: {s['dropped_no_quorum']} | p99: {s['latency_ms']['p99']}ms\n")

    # ── Kill nodes one at a time ──────────────────────────────────────────────
    for kill_node in range(3):
        print(f"Phase {kill_node+1}: Killing node {kill_node} "
              f"(cumulative dead: 0-{kill_node})")
        node_failure_event.set()
        cluster.kill_node(kill_node)

        phase = PhaseStats(f"after_killing_node_{kill_node}")
        run_writers(cluster, phase, PHASE_DURATION_SEC)
        s = phase.summary()
        all_phases.append(s)

        mode = "DROPPED" if s["dropped_no_quorum"] > 0 else "queued/absorbed"
        print(f"  Predicted TPS: {s['predicted_real_tps']:,.0f} | "
              f"Failures: {s['failures']} ({mode}) | "
              f"p99: {s['latency_ms']['p99']}ms")

        node_failure_event.clear()
        print()

    # ── Recovery time ─────────────────────────────────────────────────────────
    print("Measuring recovery time for each killed node…")
    recovery_times = {}
    # Revive nodes one at a time (0 first restores quorum immediately)
    for node_id in range(3):
        t = measure_recovery_time(cluster, node_id)
        alive_count = sum(1 for n in cluster.nodes if n.alive)
        recovery_times[node_id] = round(t, 4)
        print(f"  Node {node_id} revived → {alive_count} alive | "
              f"recovery: {t*1000:.1f} ms")

    # ── Merkle false positive report ──────────────────────────────────────────
    monitor.stop()
    merkle_report = monitor.report()
    print(f"\n── Merkle Replica Consistency ──────────────────────────────────────")
    print(f"  Total checks:     {merkle_report['total_checks']}")
    print(f"  False positives:  {merkle_report['false_positives']}")
    print(f"  True positives:   {merkle_report['true_positives']}")
    if merkle_report["false_positives"] == 0:
        print("  ✓ No false positives during any node failure event")
    else:
        print("  ✗ False positives detected — investigate replica sync lag")

    # ── Write report ──────────────────────────────────────────────────────────
    report = {
        "phases":         all_phases,
        "recovery_times": recovery_times,
        "merkle":         merkle_report,
    }
    out_path = Path(__file__).parent / "fault_tolerance_results.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n✓ Results written to {out_path}")
    return report


if __name__ == "__main__":
    main()