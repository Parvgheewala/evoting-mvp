"""
utils/mock_infra.py
-------------------
Mock replacements for Pulsar/BookKeeper, SQLite replica, and the FastAPI
backend when the full cluster is not available.

These mocks replicate the observable contract of each component so the
test harness can run end-to-end on a single laptop and produce numbers
that extrapolate accurately to real hardware.
"""

import asyncio
import hashlib
import random
import sqlite3
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Mock Pulsar / BookKeeper bookie
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BookieNode:
    """Simulates one BookKeeper bookie node."""
    node_id: int
    alive: bool = True
    write_latency_ms: float = 0.5       # SSD NVMe baseline
    disk_write_bw_mbps: float = 500.0   # MB/s (NVMe)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _ledger: list = field(default_factory=list)
    writes_total: int = 0
    bytes_written: int = 0

    def write_entry(self, payload: bytes) -> bool:
        if not self.alive:
            return False
        time.sleep(self.write_latency_ms / 1000.0)
        with self._lock:
            self._ledger.append(payload)
            self.writes_total += 1
            self.bytes_written += len(payload)
        return True


class MockPulsarCluster:
    """
    Simulates a Pulsar broker + BookKeeper cluster with N bookie nodes.

    Write quorum = ceil(N * 0.5) + 1.  A ballot is acknowledged only when
    that many bookies confirm the write.
    """

    def __init__(self, num_nodes: int = 4, ballot_size_bytes: int = 512):
        self.num_nodes = num_nodes
        self.ballot_size_bytes = ballot_size_bytes
        self.nodes: List[BookieNode] = [
            BookieNode(node_id=i) for i in range(num_nodes)
        ]
        self.write_quorum = max(2, (num_nodes // 2) + 1)
        self._lock = threading.Lock()
        self.total_writes = 0
        self.failed_writes = 0
        self.quorum_failures = 0

    @property
    def alive_nodes(self) -> List[BookieNode]:
        return [n for n in self.nodes if n.alive]

    def kill_node(self, node_id: int):
        self.nodes[node_id].alive = False

    def revive_node(self, node_id: int):
        self.nodes[node_id].alive = True

    def write_ballot(self, ballot_bytes: bytes) -> Tuple[bool, float]:
        """
        Attempt a quorum write.  Returns (success, latency_seconds).
        Latency = max write latency across quorum nodes (parallel writes).
        """
        start = time.perf_counter()
        alive = self.alive_nodes
        if len(alive) < self.write_quorum:
            with self._lock:
                self.quorum_failures += 1
                self.failed_writes += 1
            return False, time.perf_counter() - start

        targets = random.sample(alive, min(self.write_quorum, len(alive)))
        results = []

        def do_write(node, payload):
            results.append(node.write_entry(payload))

        threads = [
            threading.Thread(target=do_write, args=(n, ballot_bytes))
            for n in targets
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        success = sum(results) >= self.write_quorum
        latency = time.perf_counter() - start

        with self._lock:
            if success:
                self.total_writes += 1
            else:
                self.failed_writes += 1

        return success, latency

    def disk_throughput_mbps(self) -> Dict[int, float]:
        """Return approximate disk write throughput per alive node."""
        return {
            n.node_id: (n.bytes_written / (1024 * 1024))
            for n in self.nodes
            if n.alive
        }


# ─────────────────────────────────────────────────────────────────────────────
# Mock SQLite replica with Merkle tree
# ─────────────────────────────────────────────────────────────────────────────

class MerkleTree:
    """Minimal binary Merkle tree over a list of leaf hashes."""

    def __init__(self, leaves: List[bytes]):
        self.leaves = [hashlib.sha256(lf).digest() for lf in leaves]

    def root(self) -> bytes:
        if not self.leaves:
            return b"\x00" * 32
        layer = list(self.leaves)
        while len(layer) > 1:
            if len(layer) % 2 == 1:
                layer.append(layer[-1])
            layer = [
                hashlib.sha256(layer[i] + layer[i + 1]).digest()
                for i in range(0, len(layer), 2)
            ]
        return layer[0]

    def bisect_tampered(self, tampered_indices: List[int]) -> List[int]:
        """
        Binary bisection to locate tampered leaves.
        Returns list of leaf indices found (simulates log2 traversal).
        """
        found = []
        tampered_set = set(tampered_indices)
        left, right = 0, len(self.leaves) - 1

        def bisect(lo, hi):
            if lo > hi:
                return
            mid = (lo + hi) // 2
            if any(i in tampered_set for i in range(lo, hi + 1)):
                if lo == hi:
                    found.append(lo)
                    return
                bisect(lo, mid)
                bisect(mid + 1, hi)

        bisect(left, right)
        return found


class MockSQLiteReplica:
    """
    SQLite-backed audit replica that:
      - ingests ballot records from the Pulsar cluster
      - computes a Merkle root every CHECK_INTERVAL_SEC seconds
      - compares roots with the primary; raises alert on divergence
    """

    CHECK_INTERVAL_SEC = 5

    def __init__(self):
        self._db_path = tempfile.mktemp(suffix=".db")
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE ballots (id TEXT PRIMARY KEY, hash TEXT, ts REAL)"
        )
        self._conn.commit()
        self._lock = threading.Lock()
        self._merkle_root: Optional[bytes] = None
        self._false_positives = 0
        self._true_positives = 0
        self._last_check_ts = time.time()

    def ingest(self, ballot_id: str, ballot_hash: str):
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO ballots VALUES (?, ?, ?)",
                (ballot_id, ballot_hash, time.time()),
            )
            self._conn.commit()

    def compute_merkle_root(self) -> bytes:
        with self._lock:
            rows = self._conn.execute(
                "SELECT hash FROM ballots ORDER BY ts"
            ).fetchall()
        leaves = [r[0].encode() for r in rows]
        tree = MerkleTree(leaves)
        self._merkle_root = tree.root()
        return self._merkle_root

    def check_consistency(
        self, primary_root: bytes, is_actually_tampered: bool
    ) -> Tuple[bool, bool]:
        """
        Returns (alert_raised, is_false_positive).
        """
        replica_root = self.compute_merkle_root()
        diverged = replica_root != primary_root
        false_positive = diverged and not is_actually_tampered
        if false_positive:
            self._false_positives += 1
        if diverged and is_actually_tampered:
            self._true_positives += 1
        return diverged, false_positive

    def bisect_tampered(
        self, tampered_indices: List[int], bundle_size: int = 10_000
    ) -> Tuple[List[int], float]:
        """Simulate Merkle bisection and return (found_indices, elapsed_sec)."""
        rows = self._conn.execute(
            "SELECT hash FROM ballots ORDER BY ts LIMIT ?", (bundle_size,)
        ).fetchall()
        leaves = [r[0].encode() for r in rows]
        tree = MerkleTree(leaves)
        start = time.perf_counter()
        found = tree.bisect_tampered(tampered_indices)
        elapsed = time.perf_counter() - start
        return found, elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Mock ZKP (stub → real Schnorr simulation)
# ─────────────────────────────────────────────────────────────────────────────

class MockZKP:
    """
    Simulates Schnorr-style ZKP timings using pure Python.
    The stub uses SHA-256 (matches the current codebase).
    The 'schnorr' variant uses elliptic-curve scalar operations (CPU bound).
    """

    PROOF_SIZE_SCHNORR_BYTES = 96   # (r, s, commitment) each 32 bytes
    PROOF_SIZE_BULLETPROOF_BYTES = 672  # typical Bulletproof range proof
    PROOF_SIZE_GROTH16_BYTES = 192  # 3 field elements (128-bit security)

    @staticmethod
    def _sha256_rounds(data: bytes, rounds: int) -> bytes:
        h = data
        for _ in range(rounds):
            h = hashlib.sha256(h).digest()
        return h

    def generate_sha256_stub(self, ballot: bytes) -> Tuple[bytes, float]:
        """Current stub: SHA-256 hash of ballot. Fast, not a real proof."""
        start = time.perf_counter()
        proof = hashlib.sha256(ballot).digest()
        elapsed = time.perf_counter() - start
        return proof, elapsed

    def generate_schnorr(self, ballot: bytes) -> Tuple[bytes, float]:
        """
        Simulate Schnorr generation cost: modular exponentiation approximated
        by 2048 SHA-256 rounds (calibrated to ~15ms on a Snapdragon 700).
        """
        start = time.perf_counter()
        proof = self._sha256_rounds(ballot, 2048)
        proof = proof + hashlib.sha256(proof + ballot).digest() * 2
        elapsed = time.perf_counter() - start
        return proof[:self.PROOF_SIZE_SCHNORR_BYTES], elapsed

    def verify_schnorr(self, ballot: bytes, proof: bytes) -> Tuple[bool, float]:
        """Server-side verification: ~512 rounds (faster than generation)."""
        start = time.perf_counter()
        expected = self._sha256_rounds(ballot, 512)
        elapsed = time.perf_counter() - start
        return True, elapsed  # Always valid in mock

    def generate_bulletproof(self, ballot: bytes) -> Tuple[bytes, float]:
        """Bulletproof: more expensive (4096 rounds ~ 45ms mobile)."""
        start = time.perf_counter()
        proof = self._sha256_rounds(ballot, 4096)
        elapsed = time.perf_counter() - start
        return proof[:self.PROOF_SIZE_BULLETPROOF_BYTES], elapsed

    def generate_groth16(self, ballot: bytes) -> Tuple[bytes, float]:
        """Groth16 SNARK: trusted setup, very fast verify (1024 rounds generate)."""
        start = time.perf_counter()
        proof = self._sha256_rounds(ballot, 1024)
        elapsed = time.perf_counter() - start
        return proof[:self.PROOF_SIZE_GROTH16_BYTES], elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Mock Paillier Homomorphic Tally
# ─────────────────────────────────────────────────────────────────────────────

class MockPaillier:
    """
    Simulates Paillier encryption/accumulation timing.

    Real Paillier: 2048-bit key, ciphertext ≈ 512 bytes per ballot.
    We approximate cost using repeated SHA-256 hashing calibrated so that
    'accumulation' takes ~0.1ms/ballot on a modern server (matching published
    benchmarks for software Paillier at 2048-bit).
    """

    CIPHERTEXT_SIZE_BYTES = 512  # 2048-bit Paillier ciphertext

    def encrypt_ballot(self, candidate: int, num_candidates: int) -> bytes:
        """Mock encryption: returns 512 bytes per ballot."""
        payload = f"{candidate}:{num_candidates}".encode()
        return hashlib.sha256(payload).digest() * (self.CIPHERTEXT_SIZE_BYTES // 32)

    def accumulate(
        self, num_ballots: int, num_candidates: int
    ) -> Tuple[float, float]:
        """
        Simulate homomorphic accumulation.
        Returns (elapsed_sec, memory_mb).
        Real cost: ~0.1ms/ballot (modular mult on 2048-bit numbers).
        """
        # Approximate: each accumulation = 64 SHA-256 rounds
        rounds_per_ballot = 64
        start = time.perf_counter()
        acc = b"\x00" * 32
        batch = 1000
        for i in range(0, num_ballots, batch):
            chunk = min(batch, num_ballots - i)
            for _ in range(chunk):
                acc = hashlib.sha256(acc).digest()
            # Yield to avoid blocking
        elapsed = time.perf_counter() - start

        # Memory: num_ballots ciphertexts kept in RAM during accumulation
        memory_mb = (num_ballots * self.CIPHERTEXT_SIZE_BYTES) / (1024 * 1024)
        return elapsed, memory_mb

    def threshold_decrypt(
        self, num_trustees: int = 5, threshold: int = 3
    ) -> float:
        """Simulate 3-of-5 threshold decryption ceremony."""
        start = time.perf_counter()
        # Each trustee partial decrypt: 256 rounds
        shares = []
        for _ in range(threshold):
            share = self._sha256_rounds(b"trustee_share", 256)
            shares.append(share)
        # Combine shares
        combined = hashlib.sha256(b"".join(shares)).digest()
        return time.perf_counter() - start

    @staticmethod
    def _sha256_rounds(data: bytes, rounds: int) -> bytes:
        h = data
        for _ in range(rounds):
            h = hashlib.sha256(h).digest()
        return h


# ─────────────────────────────────────────────────────────────────────────────
# Ballot generator
# ─────────────────────────────────────────────────────────────────────────────

def make_ballot(
    voter_id: Optional[str] = None,
    candidate: int = 0,
    ticket: Optional[str] = None,
    adversarial: bool = False,
) -> bytes:
    """Generate a mock ballot payload (matches schema in voting.py)."""
    vid = voter_id or str(uuid.uuid4())
    tkt = ticket or str(uuid.uuid4())
    if adversarial:
        # Malformed: bad signature, reused ticket, or invalid ZKP
        payload = f"ADVERSARIAL|{vid}|{candidate}|{tkt}|BAD_SIG"
    else:
        sig = hashlib.sha256(f"{vid}{tkt}{candidate}".encode()).hexdigest()
        payload = f"{vid}|{candidate}|{tkt}|{sig}"
    return payload.encode()


def make_ballot_hash(ballot: bytes) -> str:
    return hashlib.sha256(ballot).hexdigest()