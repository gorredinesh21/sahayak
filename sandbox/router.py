#!/usr/bin/env python3
"""
Sahayak v2 — the Triage Layer (router).

Deterministic mode selection. No LLM, no network, no tokens: the press-the-button
layer that reads the log columns and pins {mode, reason} into the Case Brief.
The LLM's system prompt will carry: "the mode is already decided — never
re-triage; follow the protocol for the pinned mode."

Modes:
  A        debited, credit failed, reversal in flight     → narrate+verify+catch
  B        stuck past SLA / debit with no reversal        → file & chase
  C        SUCCESS with fraud signature (or user claim)   → dossier + escalate
  A_DONE   reversal already credited                      → confirm + receipt
  EXPLAIN  declined before debit (business decline)       → quick tip + retry
  WATCH    pending but still inside SLA                   → say-it-first + timer
  CLARIFY  nothing stuck found                            → ask, then re-triage
"""
import sqlite3
from datetime import datetime, timedelta

SLA_MINUTES = 30          # first SLA window for a pending payment
MODE_PROTOCOLS = {"A", "B", "C"}


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


class Router:
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    # ---------------------------------------------------------------- queries
    def candidates(self, user_id, window_hours=48):
        """Press-the-button step 1: the user's stuck-looking recent payments,
        most recent first. SUCCESS rows are included — Mode C hides inside them.
        (SQLite datetime('now') is UTC while seeds are local ISO, so the window
        is applied in Python.)"""
        rows = self.db.execute(
            """SELECT * FROM paytm_txn WHERE user_id=? AND (
                 status!='SUCCESS' OR txn_id IN (
                   SELECT n.txn_id FROM npci_switch_log n
                   JOIN beneficiary_bank_ledger b ON b.rrn=n.rrn
                   WHERE b.fraud_reports_count>0 OR b.account_status!='ACTIVE'))
               ORDER BY initiated_at DESC""",
            (user_id,)).fetchall()
        cutoff = datetime.now() - timedelta(hours=window_hours)
        return [r for r in rows if _parse(r["initiated_at"]) >= cutoff]

    def rails_for(self, txn_id):
        """All log rows for a txn, joined and named — the evidence bundle."""
        q = """
        SELECT t.txn_id, t.user_id, t.direction, t.amount_paise,
               t.remitter_vpa, t.beneficiary_vpa, t.initiated_at, t.status,
               t.app_err_msg,
               (SELECT resp_code FROM psp_gateway_log p
                 WHERE p.txn_id=t.txn_id LIMIT 1)               AS psp_code,
               (SELECT expiry_attempted FROM npci_switch_log n
                 WHERE n.txn_id=t.txn_id LIMIT 1)               AS expiry_attempted,
               r.rrn          AS debit_rrn,
               r.debit_ts     AS debit_ts,
               r.reversal_initiated_at AS reversal_initiated_at,
               r.reversal_credited_at  AS reversal_credited_at,
               r.hold_flag    AS hold_flag,
               b.credit_status AS credit_status,
               b.fail_reason  AS fail_reason,
               b.account_status AS account_status,
               b.fraud_reports_count AS fraud_reports_count
        FROM paytm_txn t
        LEFT JOIN remitter_bank_ledger r ON r.rrn = (SELECT rrn FROM npci_switch_log
                                       WHERE txn_id=t.txn_id AND leg='PSP_TO_NPCI'
                                       ORDER BY leg_ts DESC LIMIT 1)
        LEFT JOIN beneficiary_bank_ledger b ON b.rrn = (SELECT rrn FROM npci_switch_log
                                       WHERE txn_id=t.txn_id AND leg='NPCI_TO_BEN'
                                       ORDER BY leg_ts DESC LIMIT 1)
        WHERE t.txn_id = ?"""
        return self.db.execute(q, (txn_id,)).fetchone()

    def stats_for(self, user_id, beneficiary_vpa):
        row = self.db.execute(
            "SELECT * FROM txn_history_stats WHERE user_id=? AND beneficiary_vpa=?",
            (user_id, beneficiary_vpa)).fetchone()
        if row:
            return dict(row)
        # never seen each other → first-time by definition, avg from user's last 30d
        avg = self.db.execute(
            """SELECT AVG(amount_paise) FROM paytm_txn
               WHERE user_id=? AND initiated_at >= datetime('now','-30 days')""",
            (user_id,)).fetchone()[0] or 100000
        return {"first_time_beneficiary": 1, "txns_with_this_beneficiary": 0,
                "avg_amount_30d_paise": int(avg)}

    # ---------------------------------------------------------------- triage
    def triage(self, txn_id, user_claim=None):
        rails = self.rails_for(txn_id)
        assert rails, f"txn {txn_id} not found"
        stats = self.stats_for(rails["user_id"], rails["beneficiary_vpa"])
        mode, reason = self._decide(rails, stats, user_claim)
        return {
            "txn_id": txn_id,
            "rrn": rails["debit_rrn"],
            "mode": mode,
            "reason": reason,
            "is_protocol_mode": mode in MODE_PROTOCOLS,
            "user_id": rails["user_id"],
            "amount_paise": rails["amount_paise"],
            "beneficiary_vpa": rails["beneficiary_vpa"],
        }

    def _decide(self, rails, stats, user_claim):
        amount = rails["amount_paise"] or 0
        avg30 = stats.get("avg_amount_30d_paise") or 100000

        if rails["status"] == "FAILURE":
            if rails["debit_ts"] is None:
                code = rails["psp_code"] or "U30"
                return "EXPLAIN", f"declined before debit ({code}) — nothing is stuck"
            if rails["reversal_credited_at"]:
                return "A_DONE", "reversal already credited — confirm with receipt"
            if rails["reversal_initiated_at"]:
                return "A", (f"credit failed after debit, reversal in flight "
                             f"(reversal started {rails['reversal_initiated_at']})")
            return "B", "debit done but no reversal started — file & chase"

        if rails["status"] == "PENDING":
            age_min = ((datetime.now() - _parse(rails["initiated_at"])).total_seconds()
                       / 60) if rails["initiated_at"] else 0
            if age_min > SLA_MINUTES and rails["expiry_attempted"]:
                return "B", f"pending {age_min/60:.0f}h past SLA and the rails already gave up"
            if age_min > SLA_MINUTES:
                return "B", f"pending {age_min/60:.0f}h past SLA"
            return "WATCH", f"pending {age_min/60:.1f}h but inside SLA — say it first, arm timer"

        # status == SUCCESS
        signature = (
            (rails["fraud_reports_count"] or 0) > 0
            or (rails["account_status"] or "ACTIVE") != "ACTIVE"
            or (stats.get("first_time_beneficiary")
                and amount > 5 * avg30)
        )
        if signature:
            why = []
            if (rails["fraud_reports_count"] or 0) > 0:
                why.append(f"beneficiary flagged ×{rails['fraud_reports_count']}")
            if (rails["account_status"] or "ACTIVE") != "ACTIVE":
                why.append(f"account {rails['account_status']}")
            if stats.get("first_time_beneficiary") and amount > 5 * avg30:
                why.append(f"first-time beneficiary, ₹{amount/100:,.0f} = "
                           f"{amount/max(avg30,1):.0f}× their 30-day average")
            return "C", "SUCCESS with fraud signature: " + "; ".join(why)
        if user_claim in ("wrong_account", "fraud"):
            return "C", f"customer claim: {user_claim} on a successful payment"
        return "CLARIFY", "no stuck txn found — ask the customer, then re-triage"


if __name__ == "__main__":
    import sys
    r = Router(sys.argv[1] if len(sys.argv) > 1 else "sahayak.db")
    for t in r.db.execute("SELECT txn_id FROM paytm_txn WHERE is_demo_case=1"):
        verdict = r.triage(t["txn_id"])
        print(f"txn#{verdict['txn_id']:>3} → MODE {verdict['mode']:<7} | {verdict['reason']}")
