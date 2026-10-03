#!/usr/bin/env python3
"""
Sahayak event pipeline — every meaningful action writes a persisted diag_event
(the visualizer's source of truth) and pokes an in-process fan-out for SSE.

Kinds: user_action | psp | npci | payer_bank | receiver_bank | backend | db |
       memory | ai | tool | complaint | recovery
"""
import json
import sqlite3
import threading
import time
from datetime import datetime


class EventBus:
    """Shares the engine's single writer connection — one writer connection
    means no cross-connection WAL lock contention."""
    def __init__(self, db_or_path):
        if isinstance(db_or_path, sqlite3.Connection):
            self.db = db_or_path
        else:
            self.db = sqlite3.connect(db_or_path, check_same_thread=False)
            self.db.execute("PRAGMA busy_timeout=15000")
        self._lock = threading.Lock()
        self._subs = {}          # txn_id -> [queue]
        self._seq = 0

    def emit(self, txn_id, kind, actor, label, detail=None, status="ok",
             case_id=None):
        ts = datetime.now().isoformat(timespec="milliseconds")
        with self._lock:
            self._seq += 1
            for attempt in range(4):            # WAL contention retry
                try:
                    self.db.execute(
                        "INSERT INTO diag_events (txn_id, case_id, ts, seq, kind,"
                        " actor, label, detail, status) VALUES (?,?,?,?,?,?,?,?,?)",
                        (txn_id, case_id, ts, self._seq, kind, actor, label,
                         json.dumps(detail) if isinstance(detail, (dict, list))
                         else detail, status))
                    self.db.commit()
                    break
                except sqlite3.OperationalError:
                    if attempt == 3:
                        raise
                    time.sleep(0.06)
            ev = {"id": self._seq, "txn_id": txn_id, "case_id": case_id, "ts": ts,
                  "kind": kind, "actor": actor, "label": label,
                  "detail": detail, "status": status}
            for q in self._subs.get(txn_id, []):
                q.append(ev)
        return ev

    def events_for(self, txn_id, after_id=0):
        rows = self.db.execute(
            "SELECT id, txn_id, case_id, ts, kind, actor, label, detail, status "
            "FROM diag_events WHERE txn_id=? AND id>? ORDER BY id",
            (txn_id, after_id)).fetchall()
        out = []
        for r in rows:
            d = r[7]
            try:
                d = json.loads(d) if d and d.startswith(("{", "[")) else d
            except Exception:
                pass
            out.append({"id": r[0], "txn_id": r[1], "case_id": r[2], "ts": r[3],
                        "kind": r[4], "actor": r[5], "label": r[6],
                        "detail": d, "status": r[8]})
        return out

    # ------------------------------------------------------------- SSE subs
    def subscribe(self, txn_id):
        q = []
        with self._lock:
            self._subs.setdefault(txn_id, []).append(q)
        return q

    def unsubscribe(self, txn_id, q):
        with self._lock:
            lst = self._subs.get(txn_id, [])
            if q in lst:
                lst.remove(q)
