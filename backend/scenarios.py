#!/usr/bin/env python3
"""
Sahayak scenario intelligence — deterministic analysis engines that Gemini
explains but never replaces.

  wrong_recipient(txn_id, intended_vpa?)  contextual mistaken-transfer analysis
                                          (evidence features + calibrated verdict
                                          + uncertainty + clarifying questions)
  retry_safety(txn_id)                    no-debit case: is a retry safe?
  state_agreement(txn_id)                 scenario 4: payer vs receiver view
"""
import sqlite3
from datetime import datetime


class ScenarioEngines:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def _txn(self, txn_id):
        return self.db.execute(
            "SELECT * FROM paytm_txn WHERE txn_id=?", (txn_id,)).fetchone()

    def _pair_stats(self, user_id, vpa):
        r = self.db.execute(
            "SELECT first_time_beneficiary, txns_with_this_beneficiary,"
            " avg_amount_30d_paise FROM txn_history_stats WHERE user_id=? AND"
            " beneficiary_vpa=?", (user_id, vpa)).fetchone()
        return (r["first_time_beneficiary"], r["txns_with_this_beneficiary"],
                r["avg_amount_30d_paise"]) if r else (1, 0, 100000)

    def _contact(self, user_id, handle):
        r = self.db.execute(
            "SELECT times_paid, last_paid_at, saved FROM contacts WHERE user_id=?"
            " AND contact_user_id=?", (user_id, handle)).fetchone()
        return dict(zip(("times_paid", "last_paid_at", "saved"), r)) if r \
            else {"times_paid": 0, "last_paid_at": None, "saved": 0}

    def _recent_together(self, user_id, vpa, days=60):
        r = self.db.execute(
            "SELECT COUNT(*), MAX(amount_paise) FROM paytm_txn WHERE user_id=?"
            " AND beneficiary_vpa=? AND initiated_at >= datetime('now', ?)",
            (user_id, vpa, f"-{days} days")).fetchone()
        return r[0], r[1]

    # ================================================================ S1
    def wrong_recipient(self, txn_id, intended_vpa=None):
        """Evidence-based mistaken-transfer analysis. Deliberately distinct
        from fraud: unfamiliar ≠ wrong ≠ criminal. Returns calibrated verdict,
        evidence list, uncertainty, and clarifying questions."""
        t = self._txn(txn_id)
        if not t:
            return {"error": "txn not found"}
        actual = t["beneficiary_vpa"]
        user = t["user_id"]
        actual_handle = actual.split("@")[0]

        ft, paid_count, avg30 = self._pair_stats(user, actual)
        contact = self._contact(user, actual_handle)
        recent_n, recent_max = self._recent_together(user, actual)
        amount = t["amount_paise"]

        ev = []          # (supports_wrong, weight, label, detail)
        ev.append((-1, 3, "payment completed",
                   "the transfer itself succeeded at the network level"))
        if contact["times_paid"] == 0 and paid_count == 0:
            ev.append((1, 4, "never paid before",
                       "no prior transfers from this user to this beneficiary"))
        else:
            ev.append((-1, 5, "known relationship",
                       f"{max(contact['times_paid'], paid_count)} previous "
                       f"payment(s); last {contact['last_paid_at'] or 'recently'}"))
        if contact["saved"]:
            ev.append((-1, 4, "saved contact",
                       "beneficiary is in the user's saved contacts"))
        ratio = round(amount / max(avg30, 1), 1)
        if ratio >= 5:
            ev.append((1, 2, "amount anomaly",
                       f"₹{amount/100:,.0f} is {ratio}× this user's 30-day average"))
        # name-confusion signal: does an intended vpa exist and differ?
        intended_note = None
        if intended_vpa and intended_vpa != actual:
            ih = intended_vpa.split("@")[0]
            sim = self._name_similarity(ih, actual_handle)
            if sim >= 0.5:
                ev.append((1, 6, "lookalike beneficiary",
                           f"'{actual_handle}' closely resembles intended "
                           f"'{ih}' (similarity {sim:.0%}) — classic typo/wrong-pick"))
                intended_note = intended_vpa
            else:
                ev.append((0, 1, "intended differs",
                           "stated intended recipient does not resemble actual"))
        # same-city familiarity (weak signal)
        urow = self.db.execute("SELECT home_city FROM users WHERE user_id=?",
                               (user,)).fetchone()
        arow = self.db.execute("SELECT home_city FROM users WHERE user_id=?",
                               (actual_handle,)).fetchone()
        if urow and arow:
            ev.append((-1 if urow[0] == arow[0] else 1, 1,
                       "geography",
                       f"same city ({urow[0]})" if urow[0] == arow[0]
                       else f"user in {urow[0]}, beneficiary in {arow[0]}"))

        score = sum(w * d for d, w, *_ in ev)
        max_score = sum(w for d, w, *_ in ev if d) or 1
        conf = round(min(0.95, 0.35 + abs(score) / (2 * max_score)), 2)
        if score >= 8:
            verdict = "LIKELY_WRONG_RECIPIENT"
        elif score >= 4:
            verdict = "POSSIBLY_WRONG"
        elif score <= -6:
            verdict = "LIKELY_INTENDED"
        else:
            verdict = "UNCERTAIN"
        questions = []
        if not intended_vpa:
            questions.append("Who did you intend to pay? A name or UPI ID helps "
                             "me compare it with the actual recipient.")
        if verdict in ("UNCERTAIN", "POSSIBLY_WRONG") and contact["times_paid"] == 0:
            questions.append("Is this recipient someone you've paid on another "
                             "app or by cash before?")
        return {
            "verdict": verdict, "confidence": conf, "score": score,
            "evidence": [{"supports": ("wrong" if d > 0 else "intended" if d < 0
                                       else "neutral"),
                          "label": lab, "detail": det} for d, w, lab, det in ev],
            "intended_vpa": intended_note,
            "clarifying_questions": questions,
            "guardrails": [
                "completed UPI transfers cannot be auto-reversed by support",
                "recovery needs beneficiary-bank cooperation or dispute filing",
                "this analysis is evidence-based; it does not accuse anyone"],
            "deterministic": True,
        }

    @staticmethod
    def _name_similarity(a, b):
        a1, b1 = a.split(".")[0], b.split(".")[0]
        al, bl = a.split(".")[-1], b.split(".")[-1]
        s = 0.0
        if a1 == b1:
            s += .6
        elif a1[:3] == b1[:3]:
            s += .3
        if al == bl:
            s += .4
        return min(1.0, s)

    # ================================================================ S3
    def retry_safety(self, txn_id):
        """No-debit case. A retry is safe ONLY when the original is a
        confirmed terminal no-debit failure. Unknown state → verify first."""
        t = self._txn(txn_id)
        if not t:
            return {"error": "txn not found"}
        debit = self.db.execute(
            """SELECT r.debit_ts, r.debit_amount_paise FROM remitter_bank_ledger r
               JOIN npci_switch_log n ON n.rrn = r.rrn WHERE n.txn_id=?""",
            (txn_id,)).fetchone()
        debited = bool(debit and debit["debit_ts"])
        terminal_failure = t["status"] == "FAILURE"
        pending = t["status"] == "PENDING"
        if terminal_failure and not debited:
            return {"safe_to_retry": True, "reason":
                    "confirmed no-debit failure (rejected before authorization); "
                    "no funds left the account",
                    "duplicate_risk": "none — original never moved money",
                    "recommendation": "retry_enabled"}
        if pending:
            return {"safe_to_retry": False, "reason":
                    "original status is PENDING — debit state unknown; retrying "
                    "now risks a duplicate debit",
                    "duplicate_risk": "high",
                    "recommendation": "verify_first"}
        if debited and terminal_failure:
            return {"safe_to_retry": False, "reason":
                    "money WAS debited and the credit failed — a reversal is in "
                    "flight; retry would double-pay",
                    "duplicate_risk": "high",
                    "recommendation": "wait_for_reversal_or_file_dispute"}
        return {"safe_to_retry": True, "reason":
                f"state {t['status']} with no debit recorded",
                "duplicate_risk": "low", "recommendation": "retry_enabled"}

    # ================================================================ S4
    def state_agreement(self, txn_id):
        """Payer view vs receiver view. Disagreement = the scenario-4 fault."""
        t = self._txn(txn_id)
        if not t:
            return {"error": "txn not found"}
        payer_view = t["status"]
        credit = self.db.execute(
            """SELECT b.credit_status, b.credit_ts FROM beneficiary_bank_ledger b
               JOIN npci_switch_log n ON n.rrn = b.rrn WHERE n.txn_id=?""",
            (txn_id,)).fetchone()
        receiver_view = credit["credit_status"] if credit else "UNKNOWN"
        agrees = (payer_view == "SUCCESS" and receiver_view == "CREDITED") or \
                 (payer_view != "SUCCESS" and receiver_view in ("FAILED", None, "UNKNOWN"))
        return {"payer_view": payer_view,
                "receiver_view": receiver_view or "UNKNOWN",
                "agreement": "CONSISTENT" if agrees else "DISAGREEMENT",
                "explanation": None if agrees else
                "payer side shows pending while the beneficiary bank reports the "
                "credit — a reconciliation-window mismatch (the receiver may "
                "already see the money)",
                "sla_class": "reconciliation",
                "deterministic": True}
