#!/usr/bin/env python3
"""
Proactive SLA scheduler — the "never forgets" machine.

When Sahayak opens a case with an ACTIVE SLA:
  1. Registers a timer at the SLA expiry time
  2. At expiry, automatically re-checks the payment status
  3. If resolved → closes the case + notifies
  4. If still stuck → files the dispute + notifies + escalates

This is what replaces the human ops team that would set calendar reminders.
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta


class SLAScheduler:
    def __init__(self, db_or_path, services, complaints, bus=None):
        if isinstance(db_or_path, sqlite3.Connection):
            self.db = db_or_path          # share the single writer connection
        else:
            self.db = sqlite3.connect(db_or_path, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA busy_timeout=15000")
        self.S = services
        self.complaints = complaints
        self.bus = bus
        self._lock = threading.Lock()
        self._ensure_table()
        self._start_daemon()

    def _ensure_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS sla_timers (
                timer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id INTEGER NOT NULL,
                case_id TEXT,
                sla_expiry TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ARMED',
                -- ARMED → FIRED → ACTION_TAKEN / RESOLVED
                action_taken TEXT,
                notified_at TEXT,
                created_at TEXT NOT NULL
            )""")
        self.db.commit()

    def arm(self, txn_id, case_id, sla_expiry):
        """Register a timer for this transaction's SLA expiry."""
        self.db.execute(
            "INSERT INTO sla_timers (txn_id, case_id, sla_expiry, created_at) "
            "VALUES (?,?,?,?)",
            (txn_id, case_id, sla_expiry, datetime.now().isoformat()))
        self.db.commit()
        if self.bus:
            self.bus.emit(txn_id, "backend", "sla-scheduler",
                         f"SLA timer armed · fires at {sla_expiry[11:16]}",
                         {"txn_id": txn_id, "expiry": sla_expiry})

    def _start_daemon(self):
        """Background thread that checks for expired timers every 30 seconds."""
        def run():
            while True:
                try:
                    self._check_expired()
                except Exception:
                    pass
                time.sleep(30)
        t = threading.Thread(target=run, daemon=True, name="sla-scheduler")
        t.start()

    def _check_expired(self):
        now = datetime.now().isoformat()
        expired = self.db.execute(
            "SELECT * FROM sla_timers WHERE status = 'ARMED' AND sla_expiry <= ?",
            (now,)).fetchall()
        for timer in expired:
            self._fire(timer)

    def _fire(self, timer):
        """Timer fired — check status, take action, notify."""
        txn_id = timer["txn_id"]
        with self._lock:
            self.db.execute(
                "UPDATE sla_timers SET status = 'FIRED' WHERE timer_id = ?",
                (timer["timer_id"],))
            self.db.commit()

        # re-check the payment status
        payment = self.S.payment(txn_id)
        if not payment:
            self._complete(timer, "TXN_NOT_FOUND", None)
            return

        current_status = payment["status"]
        reversal_credited = payment["reversal_credited_at"]

        if current_status == "SUCCESS" or reversal_credited:
            # resolved — close and notify
            action = f"Payment resolved at {reversal_credited or 'check'}. Closing."
            self._complete(timer, "RESOLVED", action)
            if self.bus:
                self.bus.emit(txn_id, "recovery", "sla-scheduler",
                             "SLA timer: payment RESOLVED — auto-closing case",
                             {"status": current_status}, "ok")
            return

        # still stuck — file the dispute automatically
        sla = self.S.sla(txn_id)
        dispute_result = self._file_dispute(txn_id, payment)
        action = (f"SLA expired at {timer['sla_expiry'][11:16]}. "
                  f"Payment still {current_status}. "
                  f"Auto-filed dispute: {dispute_result.get('ticket_ref', 'failed')}")
        self._complete(timer, "ACTION_TAKEN", action)

        # store as a support message in the case
        if timer["case_id"]:
            self.db.execute(
                "INSERT INTO support_messages (case_id, role, text, thinking, "
                "created_at) VALUES (?,?,?,?,?)",
                (timer["case_id"], "assistant",
                 f"⏰ SLA UPDATE: The resolution deadline has passed. "
                 f"I've automatically filed a dispute ({dispute_result.get('ticket_ref')}) "
                 f"and escalated this to payments-ops. You don't need to do anything — "
                 f"I'll update you when there's progress.",
                 json.dumps([{"tool": "sla_timer_fired",
                             "detail": f"auto-filed at {timer['sla_expiry']}"}]),
                 datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

        if self.bus:
            self.bus.emit(txn_id, "complaint", "sla-scheduler",
                         f"SLA EXPIRED — dispute auto-filed: "
                         f"{dispute_result.get('ticket_ref', 'N/A')}",
                         {"action": "auto_dispute",
                          "ticket": dispute_result.get("ticket_ref")}, "warn")

    def _file_dispute(self, txn_id, payment):
        """File the NPCI-style dispute for this stuck payment."""
        rrn = self.db.execute(
            "SELECT rrn FROM npci_switch_log WHERE txn_id=?",
            (txn_id,)).fetchone()
        f = {
            "rrn": rrn["rrn"] if rrn else None,
            "txn_date": payment["initiated_at"][:10],
            "amount_paise": payment["amount_paise"],
            "payer_vpa": f"{payment['user_id']}@paytm",
            "payee_vpa": payment["beneficiary_vpa"],
            "payer_bank": payment["payer_bank"] or "HDFC Bank",
            "payee_bank": "@" + payment["beneficiary_vpa"].split("@")[-1],
            "category": "debited_not_credited",
            "description": (
                f"Auto-filed by Sahayak SLA scheduler. Payment of "
                f"₹{payment['amount_paise']/100:.0f} to "
                f"{payment['beneficiary_vpa']} is still "
                f"{payment['status']} past the SLA deadline. "
                f"Customer was debited on {payment['initiated_at'][:10]}."),
        }
        try:
            return self.complaints.submit(f, txn_id=txn_id, seed=txn_id)
        except Exception as e:
            return {"error": str(e)[:100], "ticket_ref": "FILE_FAILED"}

    def _complete(self, timer, status, action):
        self.db.execute(
            "UPDATE sla_timers SET status = ?, action_taken = ?, "
            "notified_at = ? WHERE timer_id = ?",
            (status, action, datetime.now().isoformat(), timer["timer_id"]))
        self.db.commit()

    def timers_for(self, txn_id):
        rows = self.db.execute(
            "SELECT * FROM sla_timers WHERE txn_id = ? ORDER BY created_at DESC",
            (txn_id,)).fetchall()
        return [dict(zip(r.keys(), r)) for r in rows]
