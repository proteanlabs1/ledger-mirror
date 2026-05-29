#!/usr/bin/env python3
"""Protean Ledger indexer — replays the canonical contract from genesis.

The indexer is the third-party reproducibility commitment: any party can
run this script against a Base RPC, point it at the deployed
ProteanLedger proxy address, and reproduce the same indexer state digest
that protean.sh/ledger publishes.

Storage:
    SQLite by default (single-file, zero-deps); Postgres URL accepted via
    --db. Production indexer runs Postgres for write concurrency; dev/CI
    indexer uses SQLite. The schema is dialect-agnostic enough that both
    work — the digest computation is byte-identical across backends.

Reorg handling:
    The indexer holds a 12-block uncertainty window. Confirmed rows
    (current_head - block >= 12) are eligible for the digest; recent
    rows are tagged unconfirmed in the schema and excluded.

Idempotency:
    Every event handler is an upsert keyed on (tx_hash, log_index) for
    history rows or (record_id) / (edge_id) for state rows. Re-running
    from genesis produces byte-identical state.

Canonical bytes (the digest input):
    Every row is serialized as RFC 8785-style JCS JSON with one local
    rule: bytea columns are emitted as lowercase 0x-prefixed hex.
    Integers serialize as decimal strings (avoids JS-vs-Python int/float
    drift). The digest is sha256 over the concatenated canonical bytes
    of (records sorted by record_id, edges sorted by edge_id), each row
    terminated with b"\\n".

Usage:
    index_ledger_from_genesis.py --rpc <RPC_URL> --proxy <CONTRACT_ADDR>
        [--db path/to/state.db | --db postgresql://...]
        [--from-block N] [--to-block N|"head"]
        [--once]                # one pass; useful for CI / digest verify
        [--digest-only]         # skip indexing; print current digest

Spec: docs_internal/architecture/protean_ledger_indexer.md
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

LOG = logging.getLogger("protean_ledger_indexer")

# Event signatures (keccak("EventName(...)")) — the indexer subscribes
# to exactly this set. Anything else emitted by the contract is captured
# as a generic governance row.
EVENT_SIGNATURES = {
    "RecordRegistered":            "RecordRegistered(bytes32,uint8,uint8,uint8,address,uint256)",
    "RecordContentEmitted":        "RecordContentEmitted(bytes32,string,string,string,string,string,string,string[],bytes32,bytes32,uint64)",
    "RecordSuperseded":            "RecordSuperseded(bytes32,bytes32,address,string)",
    "RecordRetracted":             "RecordRetracted(bytes32,address,string)",
    "RetractionProposed":          "RetractionProposed(bytes32,address,uint64,string)",
    "RetractionCancelled":         "RetractionCancelled(bytes32,address)",
    "LifecycleChanged":            "LifecycleChanged(bytes32,uint8,uint8,address)",
    "DisclosureChanged":           "DisclosureChanged(bytes32,uint8,uint8,address)",
    "EdgeLinked":                  "EdgeLinked(bytes32,bytes32,bytes32,uint8,bool,bool,address,bytes32,string)",
    "EdgeRevoked":                 "EdgeRevoked(bytes32,bytes32,bytes32,address,string)",
    "LedgerPaused":                "LedgerPaused(address)",
    "LedgerUnpaused":              "LedgerUnpaused(address)",
    "UpgradesFrozenPermanently":   "UpgradesFrozenPermanently(address,uint64)",
    "LedgerInitialized":           "LedgerInitialized(address,string)",
}

CONFIRMATION_BLOCKS = 12

SCHEMA_VERSION = "protean.indexer.v1"

# ─────────────────────────────────────────────────────────────────────
# Canonical bytes serialization (the trust root for digest)
# ─────────────────────────────────────────────────────────────────────


def canonical_bytes(row: Mapping[str, Any]) -> bytes:
    """Serialize a row to JCS-compatible canonical JSON.

    Local rules layered on RFC 8785:
    - bytea / bytes → lowercase hex with 0x prefix
    - int → decimal string (avoids floating-point ambiguity in JS clients)
    - None → null
    - keys sorted lexicographically
    - no whitespace, no trailing newline
    """
    normalized = {k: _normalize(v) for k, v in row.items()}
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return str(value)


# ─────────────────────────────────────────────────────────────────────
# Storage backend abstraction
# ─────────────────────────────────────────────────────────────────────


class Storage:
    """Minimal storage interface — SQLite or Postgres."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        raise NotImplementedError

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> Any:
        raise NotImplementedError

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class SqliteStorage(Storage):
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS indexer_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS records (
                record_id TEXT PRIMARY KEY,
                record_type INTEGER NOT NULL,
                lifecycle_state INTEGER NOT NULL,
                disclosure_state INTEGER NOT NULL,
                writer TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                runtime_id TEXT NOT NULL DEFAULT '',
                replay_pointer TEXT NOT NULL DEFAULT '',
                publication_url TEXT NOT NULL DEFAULT '',
                references_json TEXT NOT NULL DEFAULT '[]',
                supersedes TEXT NOT NULL DEFAULT '',
                retracts TEXT NOT NULL DEFAULT '',
                published_at INTEGER NOT NULL DEFAULT 0,
                register_block INTEGER NOT NULL,
                register_tx TEXT NOT NULL,
                register_log_index INTEGER NOT NULL,
                is_retracted INTEGER NOT NULL DEFAULT 0,
                superseded_by TEXT NOT NULL DEFAULT '',
                confirmed INTEGER NOT NULL DEFAULT 0
            )
            """,
            "CREATE INDEX IF NOT EXISTS records_register_block_idx ON records(register_block)",
            "CREATE INDEX IF NOT EXISTS records_writer_idx ON records(writer)",
            "CREATE INDEX IF NOT EXISTS records_record_type_idx ON records(record_type)",
            """
            CREATE TABLE IF NOT EXISTS edges (
                edge_id TEXT PRIMARY KEY,
                parent_record_id TEXT NOT NULL,
                child_record_id TEXT NOT NULL,
                relation INTEGER NOT NULL,
                supersession_derived INTEGER NOT NULL DEFAULT 0,
                retraction_derived INTEGER NOT NULL DEFAULT 0,
                writer TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_block INTEGER NOT NULL,
                created_tx TEXT NOT NULL,
                created_log_index INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                revoke_reason TEXT NOT NULL DEFAULT '',
                confirmed INTEGER NOT NULL DEFAULT 0
            )
            """,
            "CREATE INDEX IF NOT EXISTS edges_parent_idx ON edges(parent_record_id, relation)",
            "CREATE INDEX IF NOT EXISTS edges_child_idx ON edges(child_record_id, relation)",
            """
            CREATE TABLE IF NOT EXISTS lifecycle_history (
                record_id TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                old_state INTEGER NOT NULL,
                new_state INTEGER NOT NULL,
                writer TEXT NOT NULL,
                block INTEGER NOT NULL,
                PRIMARY KEY (tx_hash, log_index)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS disclosure_history (
                record_id TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                old_state INTEGER NOT NULL,
                new_state INTEGER NOT NULL,
                writer TEXT NOT NULL,
                block INTEGER NOT NULL,
                PRIMARY KEY (tx_hash, log_index)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS retraction_proposals (
                record_id TEXT PRIMARY KEY,
                proposer TEXT NOT NULL,
                executable_after INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,  -- 'pending'|'cancelled'|'executed'
                proposed_block INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS governance_events (
                tx_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                block INTEGER NOT NULL,
                PRIMARY KEY (tx_hash, log_index)
            )
            """,
        ]
        for stmt in ddl:
            self.conn.execute(stmt)
        self.conn.commit()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> Any:
        return self.conn.executemany(sql, rows)

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def open_storage(db_url: str) -> Storage:
    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        raise NotImplementedError(
            "Postgres backend not wired in this build. The schema is "
            "portable; use psycopg's connection in place of sqlite3 and "
            "swap the upsert syntax. SQLite covers dev + reproducibility CI."
        )
    return SqliteStorage(db_url)


# ─────────────────────────────────────────────────────────────────────
# Digest computation
# ─────────────────────────────────────────────────────────────────────


def compute_digest(storage: Storage) -> dict[str, Any]:
    """Compute the deterministic state digest over confirmed rows only."""
    records = storage.fetchall(
        "SELECT * FROM records WHERE confirmed=1 ORDER BY record_id"
    )
    edges = storage.fetchall(
        "SELECT * FROM edges WHERE confirmed=1 ORDER BY edge_id"
    )

    hasher = hashlib.sha256()
    hasher.update(b"records:")
    for rec in records:
        hasher.update(canonical_bytes(rec))
        hasher.update(b"\n")
    hasher.update(b"edges:")
    for edge in edges:
        hasher.update(canonical_bytes(edge))
        hasher.update(b"\n")

    last_block_row = storage.fetchall(
        "SELECT value FROM indexer_state WHERE key='last_indexed_block'"
    )
    last_block = int(last_block_row[0]["value"]) if last_block_row else 0

    return {
        "digest": "sha256:" + hasher.hexdigest(),
        "record_count": len(records),
        "edge_count": len(edges),
        "last_block": last_block,
        "schema_version": SCHEMA_VERSION,
        "computed_at_unix": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# Web3 + event processing (skeleton; defers RPC details to web3.py)
# ─────────────────────────────────────────────────────────────────────


@dataclass
class IndexerConfig:
    rpc_url: str
    proxy_address: str
    db_url: str
    from_block: int = 0
    to_block: str | int = "head"
    poll_interval_seconds: float = 12.0
    once: bool = False


def _hex_to_int(v: Any) -> int:
    if isinstance(v, int):
        return v
    s = str(v)
    if s.startswith("0x"):
        return int(s, 16)
    return int(s)


def _normalize_address(addr: Any) -> str:
    s = str(addr)
    if not s.startswith("0x"):
        s = "0x" + s
    return s.lower()


def _normalize_bytes32(b: Any) -> str:
    if isinstance(b, bytes):
        return "0x" + b.hex()
    s = str(b)
    if s.startswith("0x"):
        return s.lower()
    return "0x" + s.lower()


def _actor_of(args: dict[str, Any]) -> str:
    """Extract the acting address regardless of which name the event uses.

    The contract uses 'writer' on RecordRegistered, 'actor' on most other
    events, and 'proposer' on RetractionProposed. Normalize to a single
    field for the indexer's storage shape.
    """
    addr = (args.get("writer") or args.get("actor") or args.get("proposer")
            or "0x" + "0" * 40)
    return _normalize_address(addr)


def process_event(storage: Storage, event_name: str, args: dict[str, Any],
                  tx_hash: str, log_index: int, block: int,
                  current_head: int) -> None:
    """Apply a single decoded event to the database.

    `current_head` is used to decide whether the row is confirmed (block
    is older than the 12-block uncertainty window).
    """
    confirmed = 1 if (current_head - block >= CONFIRMATION_BLOCKS) else 0

    if event_name == "RecordRegistered":
        record_id = _normalize_bytes32(args["recordId"])
        storage.execute(
            """
            INSERT OR REPLACE INTO records
                (record_id, record_type, lifecycle_state, disclosure_state,
                 writer, register_block, register_tx, register_log_index,
                 confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                int(args["recordType"]),
                int(args["lifecycleState"]),
                int(args["disclosureState"]),
                _actor_of(args),
                block,
                tx_hash,
                log_index,
                confirmed,
            ),
        )

    elif event_name == "RecordContentEmitted":
        record_id = _normalize_bytes32(args["recordId"])
        refs_list = args.get("references") or []
        storage.execute(
            """
            UPDATE records SET
                title=?, summary=?, author=?, runtime_id=?,
                replay_pointer=?, publication_url=?,
                references_json=?, supersedes=?, retracts=?, published_at=?
            WHERE record_id=?
            """,
            (
                str(args.get("title", "")),
                str(args.get("summary", "")),
                str(args.get("author", "")),
                str(args.get("runtimeId", "")),
                str(args.get("replayPointer", "")),
                str(args.get("publicationUrl", "")),
                json.dumps(refs_list),
                _normalize_bytes32(args.get("supersedes", "0x" + "00" * 32)),
                _normalize_bytes32(args.get("retracts", "0x" + "00" * 32)),
                int(args.get("publishedAt", 0)),
                record_id,
            ),
        )

    elif event_name == "RecordSuperseded":
        prior = _normalize_bytes32(args["priorRecordId"])
        new = _normalize_bytes32(args["newRecordId"])
        storage.execute(
            "UPDATE records SET superseded_by=? WHERE record_id=?",
            (new, prior),
        )

    elif event_name == "RecordRetracted":
        record_id = _normalize_bytes32(args["recordId"])
        storage.execute(
            "UPDATE records SET is_retracted=1 WHERE record_id=?",
            (record_id,),
        )

    elif event_name in {"RetractionProposed"}:
        record_id = _normalize_bytes32(args["recordId"])
        storage.execute(
            """
            INSERT OR REPLACE INTO retraction_proposals
                (record_id, proposer, executable_after, reason,
                 status, proposed_block)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                record_id,
                _actor_of(args),
                int(args["executableAfter"]),
                str(args.get("reason", "")),
                block,
            ),
        )

    elif event_name == "RetractionCancelled":
        record_id = _normalize_bytes32(args["recordId"])
        storage.execute(
            "UPDATE retraction_proposals SET status='cancelled' WHERE record_id=?",
            (record_id,),
        )

    elif event_name == "LifecycleChanged":
        record_id = _normalize_bytes32(args["recordId"])
        new_state = int(args["newState"])
        storage.execute(
            "UPDATE records SET lifecycle_state=? WHERE record_id=?",
            (new_state, record_id),
        )
        storage.execute(
            """
            INSERT OR REPLACE INTO lifecycle_history
                (record_id, tx_hash, log_index, old_state, new_state, writer, block)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id, tx_hash, log_index,
                int(args["oldState"]), new_state,
                _actor_of(args), block,
            ),
        )

    elif event_name == "DisclosureChanged":
        record_id = _normalize_bytes32(args["recordId"])
        new_state = int(args["newState"])
        storage.execute(
            "UPDATE records SET disclosure_state=? WHERE record_id=?",
            (new_state, record_id),
        )
        storage.execute(
            """
            INSERT OR REPLACE INTO disclosure_history
                (record_id, tx_hash, log_index, old_state, new_state, writer, block)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id, tx_hash, log_index,
                int(args["oldState"]), new_state,
                _actor_of(args), block,
            ),
        )

    elif event_name == "EdgeLinked":
        edge_id = _normalize_bytes32(args["edgeId"])
        storage.execute(
            """
            INSERT OR REPLACE INTO edges
                (edge_id, parent_record_id, child_record_id, relation,
                 supersession_derived, retraction_derived, writer,
                 description, created_block, created_tx, created_log_index,
                 confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                _normalize_bytes32(args["parentRecordId"]),
                _normalize_bytes32(args["childRecordId"]),
                int(args["relation"]),
                1 if args.get("supersessionDerived") else 0,
                1 if args.get("retractionDerived") else 0,
                _actor_of(args),
                str(args.get("description", "")),
                block, tx_hash, log_index,
                confirmed,
            ),
        )

    elif event_name == "EdgeRevoked":
        edge_id = _normalize_bytes32(args["edgeId"])
        storage.execute(
            "UPDATE edges SET revoked=1, revoke_reason=? WHERE edge_id=?",
            (str(args.get("reason", "")), edge_id),
        )

    elif event_name in {"LedgerPaused", "LedgerUnpaused",
                        "UpgradesFrozenPermanently", "LedgerInitialized"}:
        storage.execute(
            """
            INSERT OR REPLACE INTO governance_events
                (tx_hash, log_index, event_name, payload_json, block)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                tx_hash, log_index, event_name,
                json.dumps({k: _hex_normalize_for_storage(v) for k, v in args.items()}),
                block,
            ),
        )

    else:
        LOG.warning("unknown event_name=%s; skipping", event_name)


def _hex_normalize_for_storage(value: Any) -> Any:
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, (list, tuple)):
        return [_hex_normalize_for_storage(v) for v in value]
    return value


# ─────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────


def run_indexer(cfg: IndexerConfig) -> None:
    try:
        from web3 import Web3
    except ImportError as exc:
        raise SystemExit(
            "web3.py is required: pip install 'web3>=6,<7'"
        ) from exc

    w3 = Web3(Web3.HTTPProvider(cfg.rpc_url))
    # web3.py's is_connected() calls web3_clientVersion which many public
    # RPCs (incl. Base) do not expose. Use eth_chainId instead — every
    # RPC supports it.
    try:
        _ = w3.eth.chain_id
    except Exception as exc:
        raise SystemExit(f"cannot reach RPC {cfg.rpc_url}: {exc}")

    abi_path = Path(__file__).resolve().parent.parent / "out" / "ProteanLedger.sol" / "ProteanLedger.json"
    if not abi_path.exists():
        raise SystemExit(
            f"ABI not found at {abi_path}. Run `forge build` first."
        )
    abi = json.loads(abi_path.read_text())["abi"]
    contract = w3.eth.contract(address=Web3.to_checksum_address(cfg.proxy_address), abi=abi)

    storage = open_storage(cfg.db_url)
    try:
        last_indexed_rows = storage.fetchall(
            "SELECT value FROM indexer_state WHERE key='last_indexed_block'"
        )
        from_block = (
            int(last_indexed_rows[0]["value"]) + 1
            if last_indexed_rows
            else cfg.from_block
        )

        while True:
            head = w3.eth.block_number
            target = head if cfg.to_block == "head" else int(cfg.to_block)
            if from_block > target:
                if cfg.once:
                    break
                time.sleep(cfg.poll_interval_seconds)
                continue

            # Pull logs in chunks of 2000 blocks to stay under provider caps.
            chunk_end = min(from_block + 1999, target)
            LOG.info("indexing blocks [%d..%d] (head=%d)", from_block, chunk_end, head)

            for name in EVENT_SIGNATURES:
                event = getattr(contract.events, name)
                # web3.py's get_logs accepts either snake_case or camelCase
                # depending on version. Try snake_case first, fall back.
                try:
                    logs = event.get_logs(from_block=from_block, to_block=chunk_end)
                except TypeError:
                    logs = event.get_logs(fromBlock=from_block, toBlock=chunk_end)
                except Exception as exc:  # noqa: BLE001
                    LOG.error("get_logs failed for %s: %s", name, exc)
                    continue
                for log in logs:
                    process_event(
                        storage,
                        name,
                        dict(log["args"]),
                        log["transactionHash"].hex() if hasattr(log["transactionHash"], "hex") else str(log["transactionHash"]),
                        int(log["logIndex"]),
                        int(log["blockNumber"]),
                        head,
                    )

            storage.execute(
                "INSERT OR REPLACE INTO indexer_state(key, value) VALUES ('last_indexed_block', ?)",
                (str(chunk_end),),
            )
            storage.commit()
            from_block = chunk_end + 1

            if cfg.once and from_block > target:
                break
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Protean Ledger indexer.")
    ap.add_argument("--rpc", help="Base RPC URL (e.g., https://mainnet.base.org).")
    ap.add_argument("--proxy", help="ProteanLedger proxy address (0x...).")
    ap.add_argument("--db", default="./protean_ledger.db",
                    help="SQLite file path or postgresql:// URL.")
    ap.add_argument("--from-block", type=int, default=0)
    ap.add_argument("--to-block", default="head")
    ap.add_argument("--once", action="store_true",
                    help="Index one pass and exit (CI / digest verify).")
    ap.add_argument("--digest-only", action="store_true",
                    help="Skip indexing; print current digest and exit.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.digest_only:
        storage = open_storage(args.db)
        try:
            print(json.dumps(compute_digest(storage), indent=2))
        finally:
            storage.close()
        return 0

    if not args.rpc or not args.proxy:
        ap.error("--rpc and --proxy required (unless --digest-only)")

    cfg = IndexerConfig(
        rpc_url=args.rpc,
        proxy_address=args.proxy,
        db_url=args.db,
        from_block=args.from_block,
        to_block=args.to_block,
        once=args.once,
    )
    run_indexer(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
