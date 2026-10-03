#!/usr/bin/env python3
"""
Sahayak deterministic services — the layer the spec demands:

  stages(txn_id)   -> the 7-stage payment pipeline with the exact failure stage
  sla(txn_id)      -> structured SLA object (duration/start/expiry/remaining)
  fraud(txn_id)    -> rule-based risk engine (features -> rules -> score/signals)

Everything here is deterministic, DB-grounded, and testable without any LLM.
Gemini reasons OVER these structures; it never replaces them.
"""
import sqlite3
from datetime import datetime, timedelta

# ------------------------------------------------------------------ stages
STAGES = ["initiated", "authentication", "authorization", "gateway",
          "confirmation", "settlement", "credit"]
STAGE_LABEL = {
    "initiated": "Payment Initiated", "authentication": "Authentication",
    "authorization": "Bank Authorization", "gateway": "Gateway Processing",
    "confirmation": "Payment Confirmation", "settlement": "Settlement",
    "credit": "Customer Credit",
}


class Services:
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    # ------------------------------------------------------------ raw joins
    def payment(self, txn_id):
        q = """
        SELECT t.*, u.name AS customer_name, u.mobile,
               u.state, u.home_city, u.psp_bank, u.payer_bank,
               (SELECT resp_code FROM psp_gateway_log p WHERE p.txn_id=t.txn_id
                 ORDER BY psp_ref DESC LIMIT 1) AS psp_code,
               (SELECT forwarded FROM psp_gateway_log p WHERE p.txn_id=t.txn_id
                 ORDER BY psp_ref DESC LIMIT 1) AS psp_forwarded,
               (SELECT resp_at FROM psp_gateway_log p WHERE p.txn_id=t.txn_id
                 ORDER BY psp_ref DESC LIMIT 1) AS psp_resp_at,
               n.resp_code AS switch_code, n.expiry_attempted,
               r.debit_ts, r.debit_amount_paise,
               r.reversal_initiated_at, r.reversal_credited_at,
               b.credit_status, b.fail_reason, b.account_status,
               b.fraud_reports_count,
               (SELECT resp_code FROM npci_switch_log n2 WHERE n2.txn_id=t.txn_id
                 AND n2.leg='NPCI_TO_BEN' ORDER BY leg_ts DESC LIMIT 1) AS ben_code
        FROM paytm_txn t
        LEFT JOIN users u ON u.user_id = t.user_id
        LEFT JOIN npci_switch_log n ON n.txn_id = t.txn_id AND n.leg='PSP_TO_NPCI'
        LEFT JOIN remitter_bank_ledger r ON r.rrn = n.rrn
        LEFT JOIN beneficiary_bank_ledger b ON b.rrn = (
            SELECT rrn FROM npci_switch_log WHERE txn_id=t.txn_id AND leg='NPCI_TO_BEN'
            ORDER BY leg_ts DESC LIMIT 1)
        WHERE t.txn_id = ?"""
        return self.db.execute(q, (txn_id,)).fetchone()

    # ------------------------------------------------------------- pipeline
    def stages(self, txn_id):
        """Derive the 7-stage pipeline from the log tables. Returns
        {stages:[{stage,label,status,ts,note}], failed_at, current_stage}."""
        p = self.payment(txn_id)
        if not p:
            return None
        t0 = datetime.fromisoformat(p["initiated_at"])
        out = []

        def add(stage, status, ts=None, note=""):
            out.append({"stage": stage, "label": STAGE_LABEL[stage], "status": status,
                        "ts": ts.isoformat() if ts else None, "note": note})

        code = p["switch_code"] or p["psp_code"]
        failed = p["status"] == "FAILURE"
        pending = p["status"] == "PENDING"

        # 1 initiated — always happened
        add("initiated", "done", t0)
        # 2 authentication — PIN/app auth: failed for U30-style input errors
        auth_fail = failed and p["psp_code"] in ("U30",) and p["debit_ts"] is None
        add("authentication", "failed" if auth_fail else "done",
            t0 + timedelta(milliseconds=200),
            "UPI PIN / app auth" + (" — incorrect PIN" if auth_fail else ""))
        if auth_fail:
            return self._fin(out, "authentication", p)

        # 3 authorization — remitter bank debit decision
        if failed and p["debit_ts"] is None:
            why = {"Z2": "bank declined (risk/limit)", "U16": "beneficiary blocked",
                   "Z9": "invalid UPI ID — beneficiary validation failed"}.get(
                code, f"declined ({code or p['psp_code']})")
            add("authorization", "failed", t0 + timedelta(seconds=1), why)
            return self._fin(out, "authorization", p)
        add("authorization", "done",
            datetime.fromisoformat(p["debit_ts"]) if p["debit_ts"]
            else t0 + timedelta(seconds=1), "account debited" if p["debit_ts"] else "")

        # 4 gateway — NPCI switch forwarded the message
        gw_pending = pending and p["expiry_attempted"] in (0, 1)
        if p["psp_forwarded"] == 0:
            add("gateway", "failed", t0 + timedelta(milliseconds=400),
                f"gateway declined ({p['psp_code']})")
            return self._fin(out, "gateway", p)
        if failed and code == "Z6":
            add("gateway", "failed", t0 + timedelta(seconds=2),
                "NPCI switch unavailable (Z6) — message lost in transit")
            return self._fin(out, "gateway", p)
        if pending and p["credit_status"] is None and (
                code in ("T1", "Z6", "U50") or code is None):
            add("gateway", "timeout", t0 + timedelta(seconds=2),
                f"switch gave no response ({code or 'T1'}); auto-expiry "
                + ("already attempted" if p["expiry_attempted"] else "pending"))
            return self._fin(out, "gateway", p)
        add("gateway", "done", t0 + timedelta(seconds=2), "routed via NPCI")

        # 5 confirmation — beneficiary bank credit response
        if p["credit_status"] == "FAILED":
            add("confirmation", "failed", t0 + timedelta(seconds=4),
                f"beneficiary bank declined credit ({p['ben_code'] or code}: "
                f"{p['fail_reason'] or 'technical'})")
            return self._fin(out, "confirmation", p)
        if pending:
            add("confirmation", "waiting", None, "awaiting confirmation")
            return self._fin(out, "confirmation", p)
        add("confirmation", "done", t0 + timedelta(seconds=4), "credit confirmed")

        # 6 settlement
        batch = self.db.execute(
            "SELECT settlement_batch_id FROM npci_switch_log WHERE txn_id=? "
            "AND settlement_batch_id IS NOT NULL LIMIT 1", (txn_id,)).fetchone()
        add("settlement", "done" if batch else "waiting",
            None, batch["settlement_batch_id"] if batch else "net settlement window")

        # 7 credit — the customer-visible end state
        if p["status"] == "SUCCESS":
            note = "beneficiary credited"
            if p["reversal_credited_at"]:
                note = f"auto-reversal credited {p['reversal_credited_at'][:16]}"
            add("credit", "done", None, note)
        else:
            add("credit", "failed", None, "not credited")
        return self._fin(out, None, p)

    @staticmethod
    def _fin(stages, failed_at, p):
        cur = None
        for s in stages:
            if s["status"] in ("done",):
                cur = s["stage"]
            elif s["status"] in ("waiting", "timeout") and cur is None:
                cur = s["stage"]
        return {"stages": stages, "failed_at": failed_at,
                "current_stage": stages[-1]["stage"], "payment_status": p["status"]}

    # ------------------------------------------------------------------ SLA
    SLA_RULES = {  # hours, by outcome class
        "reversal": 24,       # debited + credit failed -> auto-reversal T+1
        "pending_first": 0.5, # pending first SLA (auto-expiry window)
        "pending_full": 24,   # pending past first SLA -> resolution SLA
        "validation": 2,      # failed before debit (retry/advice window)
        "fraud_review": 48,   # fraud/dispute review
    }

    def sla(self, txn_id):
        p = self.payment(txn_id)
        if not p:
            return None
        t0 = datetime.fromisoformat(p["initiated_at"])
        code = p["switch_code"] or p["psp_code"] or ""
        if p["status"] == "SUCCESS":
            cls, hours = ("fraud_review", self.SLA_RULES["fraud_review"]) \
                if (p["fraud_reports_count"] or 0) > 0 else (None, 0)
            if cls is None:
                return {"applicable": False, "reason": "payment succeeded; no SLA clock"}
        elif p["debit_ts"] and p["credit_status"] == "FAILED":
            cls, hours = "reversal", self.SLA_RULES["reversal"]
        elif p["status"] == "PENDING":
            age_h = (datetime.now() - t0).total_seconds() / 3600
            cls, hours = ("pending_full", self.SLA_RULES["pending_full"]) \
                if age_h > self.SLA_RULES["pending_first"] \
                else ("pending_first", self.SLA_RULES["pending_first"])
        else:
            cls, hours = "validation", self.SLA_RULES["validation"]

        expiry = t0 + timedelta(hours=hours)
        now = datetime.now()
        remaining = (expiry - now).total_seconds()
        return {
            "applicable": True, "class": cls,
            "sla_duration": f"{hours:g} hours" if hours < 48 else "48 hours",
            "sla_start": t0.isoformat(), "sla_expiry": expiry.isoformat(),
            "current_time": now.isoformat(),
            "remaining_seconds": int(remaining),
            "remaining_human": self._rem(remaining),
            "status": "ACTIVE" if remaining > 0 else "EXPIRED",
        }

    @staticmethod
    def _rem(sec):
        if sec <= 0:
            return "breached"
        h, m = int(sec // 3600), int(sec % 3600 // 60)
        return f"{h}h {m}m" if h else f"{m}m"

    # ---------------------------------------------------------------- fraud
    FRAUD_RULES = [
        # (rule_id, description, weight, predicate(features)->bool)
        ("R1_FIRST_TIME_BENEFICIARY", "First-ever payment to this beneficiary", 15,
         lambda f: f["first_time_beneficiary"]),
        ("R2_AMOUNT_ANOMALY", "Amount far above customer's 30-day average", 25,
         lambda f: f["amount_ratio"] >= 5),
        ("R3_BENEFICIARY_REPORTS", "Beneficiary VPA has public fraud reports", 30,
         lambda f: f["fraud_reports_count"] > 0),
        ("R4_ACCOUNT_NOT_ACTIVE", "Beneficiary account frozen / KYC-lapsed", 20,
         lambda f: f["account_status"] != "ACTIVE"),
        ("R5_NEW_DEVICE", "Payment from a device not seen before", 10,
         lambda f: f["new_device"]),
        ("R6_NIGHT_TIME", "Unusual hour (midnight–5am)", 10,
         lambda f: f["night_hour"]),
        ("R7_HIGH_VELOCITY", "Multiple payments in the last hour", 15,
         lambda f: f["txns_last_hour"] >= 3),
    ]

    def fraud(self, txn_id):
        p = self.payment(txn_id)
        if not p:
            return None
        t0 = datetime.fromisoformat(p["initiated_at"])
        stats = self.db.execute(
            "SELECT * FROM txn_history_stats WHERE user_id=? AND beneficiary_vpa=?",
            (p["user_id"], p["beneficiary_vpa"])).fetchone()
        avg30 = stats["avg_amount_30d_paise"] if stats else 100000
        first_time = bool(stats["first_time_beneficiary"]) if stats else True
        known_devices = [r[0] for r in self.db.execute(
            "SELECT DISTINCT device_id FROM paytm_txn WHERE user_id=? AND txn_id!=?",
            (p["user_id"], txn_id))]
        vel = self.db.execute(
            "SELECT COUNT(*) FROM paytm_txn WHERE user_id=? AND initiated_at>=?",
            (p["user_id"], (t0 - timedelta(hours=1)).isoformat())).fetchone()[0]
        f = {
            "amount_ratio": round((p["amount_paise"] or 0) / max(avg30, 1), 1),
            "avg_amount_30d_paise": avg30,
            "first_time_beneficiary": first_time,
            "fraud_reports_count": p["fraud_reports_count"] or 0,
            "account_status": p["account_status"] or "ACTIVE",
            "new_device": bool(known_devices) and p["device_id"] not in known_devices,
            "night_hour": t0.hour < 5,
            "txns_last_hour": vel,
        }
        signals, score, triggered = [], 0, []
        for rid, desc, w, pred in self.FRAUD_RULES:
            if pred(f):
                score += w
                triggered.append(rid)
                signals.append({"rule": rid, "description": desc, "weight": w})
        category = ("CRITICAL" if score >= 60 else "HIGH" if score >= 40
                    else "MEDIUM" if score >= 20 else "LOW")
        action = {
            "CRITICAL": "Hold review — escalate to risk desk before any automated action",
            "HIGH": "Escalate to risk desk with complete case file; guide customer through verification",
            "MEDIUM": "Flag for verification; notify customer with safety guidance",
            "LOW": "No fraud action required",
        }[category]
        return {"score": score, "category": category, "signals": signals,
                "triggered_rules": triggered, "features": f,
                "recommended_action": action,
                "deterministic": True,
                "note": "Rule-based engine; Gemini explains these signals, "
                        "it does not decide them."}
