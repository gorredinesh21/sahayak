#!/usr/bin/env python3
"""
Sahayak complaint / SLA workflow — a faithful SIMULATION of the documented
NPCI UPI dispute process (clearly labelled simulated=1 in every record).

Stages mirror the real flow:
  1 VALIDATE   required fields present (RRN 12-digit, date, amount, VPAs,
               payer/receiver banks, category, description >= 20 chars)
  2 BUILD      the dispute payload in the documented shape
  3 SUBMIT     through the (simulated) complaint gateway: auth header,
               idempotency key, latency, HTTP-style responses
  4 ACK        complaint number in the real format; persisted with api log
  5 TRACK      ACCEPTED -> UNDER_REVIEW -> RESOLVED (time-based progression)

No external service is contacted; nothing here claims a real bank filing.
"""
import hashlib
import json
import random
import sqlite3
from datetime import datetime, timedelta

CATEGORIES = {
    "debited_not_credited": "Transaction debited but beneficiary not credited",
    "wrong_beneficiary": "Funds transferred to wrong UPI ID",
    "delayed_credit": "Beneficiary credit delayed beyond T+1",
    "status_unclear": "Transaction status ambiguous / payer-receiver mismatch",
}

REQUIRED = ["rrn", "txn_date", "amount_paise", "payer_vpa", "payee_vpa",
            "payer_bank", "payee_bank", "category", "description"]


class ComplaintError(Exception):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage


class ComplaintService:
    """Simulated NPCI-style dispute gateway. Deterministic when seeded."""

    def __init__(self, db: sqlite3.Connection, bus=None):
        self.db = db
        self.bus = bus

    def _log(self, complaint_id, stage, payload=None, api=None, ticket=None,
             status=None, txn_id=None):
        self.db.execute(
            "INSERT INTO complaint_requests (complaint_id, txn_id, rrn, stage,"
            " payload_json, api_log_json, ticket_ref, status, submitted_at, simulated)"
            " VALUES (?,?,?,?,?,?,?,?,?,1)"
            " ON CONFLICT (complaint_id) DO UPDATE SET stage=excluded.stage,"
            " payload_json=COALESCE(excluded.payload_json, complaint_requests.payload_json),"
            " api_log_json=excluded.api_log_json, ticket_ref=excluded.ticket_ref,"
            " status=COALESCE(excluded.status, complaint_requests.status)",
            (complaint_id, txn_id, payload and payload.get("rrn"), stage,
             json.dumps(payload) if payload else None,
             json.dumps(api), ticket, status or "SUBMITTED",
             datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    # ------------------------------------------------------------ validate
    def validate(self, f: dict):
        missing = [k for k in REQUIRED if not f.get(k)]
        if missing:
            raise ComplaintError("VALIDATE",
                                 f"missing required fields: {', '.join(missing)}")
        if not (len(str(f["rrn"])) == 12 and str(f["rrn"]).isdigit()):
            raise ComplaintError("VALIDATE", "RRN must be a 12-digit reference")
        if f.get("category") not in CATEGORIES:
            raise ComplaintError("VALIDATE",
                                 f"category must be one of {list(CATEGORIES)}")
        if len(str(f.get("description", ""))) < 20:
            raise ComplaintError("VALIDATE",
                                 "description must be at least 20 characters")
        if f.get("amount_paise", 0) <= 0:
            raise ComplaintError("VALIDATE", "amount must be positive")
        return True

    # --------------------------------------------------------------- build
    def build_payload(self, f: dict):
        return {
            "disputeRequest": {
                "rrn": str(f["rrn"]),
                "txnDate": f["txn_date"],
                "amount": f["amount_paise"],
                "payerVpa": f["payer_vpa"],
                "payeeVpa": f["payee_vpa"],
                "payerBank": f["payer_bank"],
                "payeeBank": f["payee_bank"],
                "disputeCategory": f["category"],
                "disputeSubCategory": CATEGORIES[f["category"]],
                "narration": f["description"],
                "channel": "TPAP",
                "app": "PAYTM",
            }
        }

    # -------------------------------------------------------------- submit
    def submit(self, f: dict, txn_id=None, seed=None):
        """Full documented workflow. Returns the ack record. Simulated."""
        cid = "CMP-" + hashlib.sha1(
            (str(f["rrn"]) + f["category"] + str(seed or "")).encode()
        ).hexdigest()[:8].upper()
        self.validate(f)                                     # stage 1
        self._log(cid, "VALIDATED", txn_id=txn_id)
        payload = self.build_payload(f)                      # stage 2
        idem = hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:24]
        self._log(cid, "BUILT", payload=payload["disputeRequest"], txn_id=txn_id)
        # stage 3 — simulated gateway call (auth, idempotency, latency, http)
        rng = random.Random(seed or f["rrn"])
        ms = rng.randint(700, 2100)
        http = {"method": "POST",
                "endpoint": "https://sim.npci.org.in/upi/dispute/v1/complaints",
                "auth": "Bearer **** (simulated)",
                "idempotency_key": idem, "latency_ms": ms,
                "simulated": True}
        # stage 4 — ack with the real-format complaint number
        ticket = f"NPCI-{f['rrn']}-{cid[-4:]}"
        http["response"] = {"http_status": 201, "complaintNumber": ticket,
                            "status": "ACCEPTED"}
        self._log(cid, "ACKED", payload=payload["disputeRequest"], api=http,
                  ticket=ticket, status="ACCEPTED", txn_id=txn_id)
        if self.bus and txn_id:
            self.bus.emit(txn_id, "complaint", "npci-dispute-gateway",
                          f"Dispute submitted · {ticket}",
                          {"category": f["category"], "ticket": ticket,
                           "http": 201, "simulated": True,
                           "latency_ms": ms}, "ok")
        return {"complaint_id": cid, "ticket_ref": ticket, "status": "ACCEPTED",
                "payload": payload["disputeRequest"], "api": http,
                "simulated": True}

    # --------------------------------------------------------------- track
    def status(self, complaint_id):
        row = self.db.execute(
            "SELECT stage, ticket_ref, status, submitted_at, api_log_json,"
            " payload_json FROM complaint_requests WHERE complaint_id=?",
            (complaint_id,)).fetchone()
        if not row:
            return None
        # documented progression: ACCEPTED -> UNDER_REVIEW (4h) -> RESOLVED (T+3)
        age_h = (datetime.now() - datetime.fromisoformat(row[3])).total_seconds() / 3600 \
            if row[3] else 0
        status = row[2] or "ACCEPTED"
        if status == "ACCEPTED" and age_h > 4:
            status = "UNDER_REVIEW"
        if status == "UNDER_REVIEW" and age_h > 72:
            status = "RESOLVED"
        if status != row[2]:
            self.db.execute("UPDATE complaint_requests SET status=? WHERE complaint_id=?",
                            (status, complaint_id))
            self.db.commit()
        return {"complaint_id": complaint_id, "stage": row[0], "ticket_ref": row[1],
                "status": status, "submitted_at": row[3],
                "sla": {"under_review_by": "+4 hours",
                        "resolution_by": "T+3 (72 hours)",
                        "source": "simulated documented process"},
                "simulated": True}
