#!/usr/bin/env python3
"""
Sahayak v2 — live payment engine.

A payment made in the app is a REAL transaction through the mock rails:
rows are written across all five log tables, causally consistent with the
outcome (which leg broke, when, which code, whether reversal fired).

Finalization is lazy: /api/pay writes the txn + PSP hop and returns while the
payment is visibly "Processing"; the first status poll after PROCESS_DELAY
seconds writes the remaining legs. No threads, restart-tolerant.

Scenario forcing (dev drawer / demo choreography):
  auto            draw the outcome from the real calibrated rates
  success         force SUCCESS
  mode_a          force Z5 debited-not-credited, reversal in flight (now)
  mode_b_yesterday force T1 pending, timestamps 31h in the past (debit done,
                  auto-expiry already attempted — triages to Mode B)
  u30             force wrong-PIN business decline (no debit)
Mode C needs no forcing: pay to a fraud-VPA and SUCCESS — the signature
lives in the data (fraud_reports_count / first-time / amount anomaly).
"""
import os
import random
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get(
    "SAHAYAK_DB",
    os.path.join(os.path.dirname(__file__), "..", "sandbox", "sahayak.db"))
PROCESS_DELAY = 2.4  # seconds of visible "Processing" before legs finalize

BANK_TD = {
    "@okhdfcbank": 0.0008, "@okicici": 0.0020, "@okkotak": 0.0030,
    "@okaxis": 0.0040, "@oksbi": 0.0060, "@okybl": 0.0100,
    "@okpnbsk": 0.0120, "@bandhan": 0.0250, "@jio": 0.0720, "@airtel": 0.0730,
}
BD_RATE = 0.093
TD_CODE_MIX = {"Z5": 0.45, "Z8": 0.05, "T1": 0.25, "Z6": 0.15, "U50": 0.10}

MERCHANT_DISPLAY = {
    "store.paytm@ybl": "PAYTM STORE", "kirana@oksbi": "KIRANA STORE",
    "swiggy.pay@okhdfcbank": "SWIGGY", "amazonpay@okaxis": "AMAZON PAY",
    "zomato.pay@okhdfcbank": "ZOMATO", "bigbazaar@okybl": "BIG BAZAAR",
    "medplus@okicici": "MEDPLUS PHARMACY", "irctc.rail@okicici": "IRCTC",
    "petrol.pump@okaxis": "HP PETROL PUMP", "electricbill@oksbi": "TS TRANSCO",
    "dmart@okkotak": "DMART", "uber.pay@okhdfcbank": "UBER INDIA",
    "amazonretail@okhdfcbank": "AMAZON RETAIL", "apollo.pharm@okicici": "APOLLO PHARMACY",
    "burgerking@okaxis": "BURGER KING", "jio.recharge@jio": "JIO RECHARGE",
    "airtel.postpaid@airtel": "AIRTEL POSTPAID", "tsrtcbus@okicici": "TSRTC",
    "waterbill@oksbi": "HMWSSB WATER", "decathlon.hyd@okhdfcbank": "DECATHLON",
    "petromax@okaxis": "PETROMAX FUELS", "campusstore@okhdfcbank": "CAMPUS STORE",
    "laundrywala@oksbi": "SPARKLE LAUNDRY", "studioclick@okkotak": "STUDIO CLICK",
    "quickloan.help@ybl": "QUICKLOAN HELPDESK",
}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class PayEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=5000")

    # ------------------------------------------------------------- wallet
    def _wallet(self, user_id, txn_id, delta_paise, kind, at):
        """Money actually moves: one ledger row per balance change."""
        self.db.execute(
            "INSERT OR IGNORE INTO wallet_ledger (user_id, txn_id, delta_paise, kind, created_at) "
            "VALUES (?,?,?,?,?)", (user_id, txn_id, delta_paise, kind, iso(at)))
        self.db.commit()

    def _internal_user_for_vpa(self, vpa):
        """A @paytm VPA whose handle is one of our users -> internal transfer."""
        if not vpa.endswith("@paytm"):
            return None
        handle = vpa.split("@")[0]
        row = self.db.execute("SELECT user_id FROM users WHERE user_id=?",
                              (handle,)).fetchone()
        return row["user_id"] if row else None

    def _credit_beneficiary(self, txn_id, payer_id, ben_vpa, amount, at):
        ben = self._internal_user_for_vpa(ben_vpa)
        if not ben:
            return
        self._wallet(ben, txn_id, amount, "payin", at)
        payer_vpa = f"{payer_id}@paytm"
        t = (self.db.execute("SELECT MAX(txn_id) m FROM paytm_txn")
             .fetchone()["m"] or 0) + 1
        self.db.execute(
            "INSERT INTO paytm_txn (txn_id, user_id, direction, amount_paise,"
            " remitter_vpa, beneficiary_vpa, initiated_at, status, app_err_msg,"
            " device_id, is_demo_case, entry_type)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,0,'credit')",
            (t, ben, "P2P", amount, payer_vpa, payer_vpa, iso(at), "SUCCESS",
             None, f"dev_{ben}"))
        self.db.commit()

    # ------------------------------------------------------------- helpers
    def next_txn_id(self):
        return (self.db.execute("SELECT MAX(txn_id) m FROM paytm_txn").fetchone()["m"] or 0) + 1

    def next_rrn(self, at):
        seq = (self.db.execute("SELECT COUNT(*) c FROM npci_switch_log").fetchone()["c"] or 0) + 1
        return f"{at.month:02d}{at.day:02d}{seq % 100000000:08d}"

    def resolve(self, vpa):
        """VPA → display name (the 'verify before pay' step)."""
        vpa = vpa.strip()
        if "@" not in vpa:
            return None
        if vpa in MERCHANT_DISPLAY:
            return {"name": MERCHANT_DISPLAY[vpa], "kind": "merchant"}
        handle = vpa.split("@")[0]
        row = self.db.execute("SELECT name FROM users WHERE user_id=?", (handle,)).fetchone()
        if row:
            return {"name": row["name"].upper(), "kind": "person"}
        first = handle.split(".")[0].capitalize()
        if first.isalpha():
            return {"name": (first + " " + handle.split(".")[-1][:4].upper() + ".").strip(), "kind": "person"}
        return None

    # ------------------------------------------------------------- payment
    def pay(self, user_id, vpa, amount_paise, pin, scenario="auto"):
        now = datetime.now()
        if pin == "0000":
            return self._decline_pin(user_id, vpa, amount_paise, now)

        at = now - timedelta(hours=31) if scenario == "mode_b_yesterday" else now
        txn_id = self.next_txn_id()
        direction = "P2M" if vpa in MERCHANT_DISPLAY else "P2P"
        self.db.execute(
            "INSERT INTO paytm_txn (txn_id, user_id, direction, amount_paise,"
            " remitter_vpa, beneficiary_vpa, initiated_at, status, app_err_msg,"
            " device_id, is_demo_case) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
            (txn_id, user_id, direction, amount_paise, f"{user_id}@paytm", vpa,
             iso(at), "PENDING", None, f"dev_{user_id.split('.')[0]}"))
        self.db.execute(  # PSP hop: request received, no response yet
            "INSERT INTO psp_gateway_log VALUES (?,?,?,?,?,?)",
            (txn_id, txn_id, iso(at), None, None, 1))
        self.db.execute(  # bare switch row: the message is "in flight"
            "INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
            (self.next_rrn(at), txn_id, "PSP_TO_NPCI", None, iso(at), 0, None))
        self.db.commit()

        # decide the outcome now; finalize lazily on the next status poll
        decision = self._decide(vpa, scenario, at)
        _PENDING[txn_id] = (decision, at, amount_paise, vpa, direction)
        if scenario == "mode_b_yesterday":
            self.finalize_if_due(txn_id)   # age already past the delay
        return txn_id

    def _decline_pin(self, user_id, vpa, amount_paise, now):
        txn_id = self.next_txn_id()
        self.db.execute(
            "INSERT INTO paytm_txn (txn_id, user_id, direction, amount_paise,"
            " remitter_vpa, beneficiary_vpa, initiated_at, status, app_err_msg,"
            " device_id, is_demo_case) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
            (txn_id, user_id, "P2P" if vpa not in MERCHANT_DISPLAY else "P2M",
             amount_paise, f"{user_id}@paytm", vpa, iso(now), "FAILURE",
             "Incorrect UPI PIN", f"dev_{user_id.split('.')[0]}"))
        self.db.execute("INSERT INTO psp_gateway_log VALUES (?,?,?,?,?,?)",
                        (txn_id, txn_id, iso(now), iso(now + timedelta(milliseconds=340)),
                         "U30", 0))
        self.db.commit()
        _PENDING[txn_id] = ("done_u30", now, amount_paise, vpa, "P2P")
        return txn_id

    def _decide(self, vpa, scenario, at):
        if scenario in ("success", "mode_a", "mode_b_yesterday"):
            return scenario
        if scenario == "u30":
            return "u30"
        suffix = "@" + vpa.split("@")[-1]
        td = BANK_TD.get(suffix, 0.006)
        if at.hour in (20, 21, 22):
            td *= 1.3
        r = random.random()
        if r < td:
            code = random.choices(list(TD_CODE_MIX), weights=TD_CODE_MIX.values())[0]
            return "td_" + code
        if r < td + BD_RATE:
            return "bd"
        return "success"

    # --------------------------------------------------------- finalization
    def finalize_if_due(self, txn_id):
        """Called from status polls. Writes the full causal story once the
        processing delay has elapsed; idempotent."""
        info = _PENDING.get(txn_id)
        if info is None:
            return None
        decision, at, amount, vpa, direction = info
        now = datetime.now()
        if decision != "mode_b_yesterday" and (now - at).total_seconds() < PROCESS_DELAY:
            return None
        if _DONE.get(txn_id):
            return _DONE[txn_id]
        if decision == "done_u30":               # already fully written at pay()
            _DONE[txn_id] = {"status": "FAILURE", "code": "U30"}
            del _PENDING[txn_id]
            return _DONE[txn_id]

        out = self._write_outcome(txn_id, decision, at, amount, vpa, direction)
        _DONE[txn_id] = out
        del _PENDING[txn_id]
        return out

    def _write_outcome(self, txn_id, decision, at, amount, vpa, direction):
        db = self.db
        rrn_debit = db.execute(
            "SELECT rrn FROM npci_switch_log WHERE txn_id=? AND leg='PSP_TO_NPCI'",
            (txn_id,)).fetchone()["rrn"]

        def upd_psp(code, ms):
            db.execute("UPDATE psp_gateway_log SET resp_at=?, resp_code=? WHERE txn_id=?",
                       (iso(at + timedelta(milliseconds=ms)), code, txn_id))

        def write_credit_leg(code, status, reason=None, acct="ACTIVE", reports=0):
            rrn = self.next_rrn(at)
            ts = at + timedelta(seconds=4)
            db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                       (rrn, txn_id, "NPCI_TO_BEN", code, iso(ts), 0,
                        "SETTLE-" + at.strftime("%Y%m%d") if status == "CREDITED" else None))
            db.execute("INSERT INTO beneficiary_bank_ledger VALUES (?,?,?,?,?,?)",
                       (rrn, iso(ts) if status != "FAILED" else None, status, reason,
                        acct, reports))
            return rrn

        debit_wallet_done = []
        # --- debit leg: the money leaves (except clean declines)
        def write_debit(code="00"):
            db.execute("UPDATE npci_switch_log SET resp_code=?, leg_ts=? WHERE rrn=?",
                       (code, iso(at + timedelta(seconds=2)), rrn_debit))
            db.execute("INSERT OR REPLACE INTO remitter_bank_ledger VALUES (?,?,?,?,?,?)",
                       (rrn_debit, iso(at + timedelta(seconds=2)), amount,
                        None, None, 0))
            if not debit_wallet_done:
                debit_wallet_done.append(1)
                owner = db.execute("SELECT user_id FROM paytm_txn WHERE txn_id=?",
                                   (txn_id,)).fetchone()["user_id"]
                self._wallet(owner, txn_id, -amount, "payout", at)

        if decision in ("success", "mode_a", "mode_b_yesterday", "td_Z5", "td_Z8"):
            upd_psp("00", 420)
            if decision == "success":
                write_debit()
                write_credit_leg("00", "CREDITED", acct="ACTIVE")
                db.execute("UPDATE paytm_txn SET status='SUCCESS' WHERE txn_id=?", (txn_id,))
                db.commit()
                owner = db.execute("SELECT user_id FROM paytm_txn WHERE txn_id=?",
                                   (txn_id,)).fetchone()["user_id"]
                self._wallet(owner, txn_id, -amount, "payout", at)
                self._credit_beneficiary(txn_id, owner, vpa, amount, at)
                return {"status": "SUCCESS"}
            if decision in ("td_Z5", "td_Z8", "mode_a"):
                code = "Z5" if decision in ("mode_a", "td_Z5") else "Z8"
                write_debit()
                db.execute("UPDATE remitter_bank_ledger SET reversal_initiated_at=? "
                           "WHERE rrn=?", (iso(at + timedelta(minutes=10)), rrn_debit))
                write_credit_leg(code, "FAILED",
                                 "technical" if code == "Z5" else "limit")
                db.execute("UPDATE paytm_txn SET status='FAILURE', "
                           "app_err_msg='Money debited but not credited' WHERE txn_id=?",
                           (txn_id,))
                db.commit()
                return {"status": "FAILURE", "code": code}
            # mode_b_yesterday — T1: debit done, ack lost, rails gave up
            write_debit()
            db.execute("UPDATE npci_switch_log SET expiry_attempted=1 WHERE rrn=?",
                       (rrn_debit,))
            db.execute("UPDATE paytm_txn SET app_err_msg='Payment processing' "
                       "WHERE txn_id=?", (txn_id,))
            db.commit()
            return {"status": "PENDING", "code": "T1"}

        if decision in ("td_T1", "td_U50", "td_Z6"):
            upd_psp(None, 30000)  # gateway timeout
            write_debit()
            db.execute("UPDATE npci_switch_log SET expiry_attempted=0 WHERE rrn=?",
                       (rrn_debit,))
            db.execute("UPDATE paytm_txn SET app_err_msg='Payment processing' "
                       "WHERE txn_id=?", (txn_id,))
            db.commit()
            return {"status": "PENDING", "code": decision.split("_")[1]}

        if decision in ("bd", "u30"):
            code = "U30"
            upd_psp(code, 340)
            db.execute("UPDATE paytm_txn SET status='FAILURE', "
                       "app_err_msg='Incorrect UPI PIN' WHERE txn_id=?", (txn_id,))
            db.commit()
            return {"status": "FAILURE", "code": code}

        db.commit()
        return {"status": "PENDING"}

    # ------------------------------------------------------------- queries
    def txn_view(self, txn_id):
        out = self.finalize_if_due(txn_id)   # lazy completion FIRST — fresh read after
        t = self.db.execute("SELECT * FROM paytm_txn WHERE txn_id=?", (txn_id,)).fetchone()
        if not t:
            return None
        rrn = self.db.execute(
            "SELECT rrn FROM npci_switch_log WHERE txn_id=? AND leg='PSP_TO_NPCI'",
            (txn_id,)).fetchone()
        debit = self.db.execute(
            """SELECT r.* FROM remitter_bank_ledger r JOIN npci_switch_log n
               ON n.rrn=r.rrn WHERE n.txn_id=?""", (txn_id,)).fetchone()
        credit = self.db.execute(
            """SELECT b.* FROM beneficiary_bank_ledger b JOIN npci_switch_log n
               ON n.rrn=b.rrn WHERE n.txn_id=?""", (txn_id,)).fetchone()
        processing = txn_id in _PENDING
        code = None
        if credit is not None and credit["credit_status"] == "FAILED":
            row = self.db.execute(
                "SELECT resp_code FROM npci_switch_log WHERE txn_id=? AND leg='NPCI_TO_BEN'",
                (txn_id,)).fetchone()
            code = row["resp_code"] if row else None
        if code is None:
            code = (out or {}).get("code")
        return {
            "txn_id": txn_id,
            "status": "PENDING" if processing else t["status"],
            "processing": processing,
            "amount_paise": t["amount_paise"],
            "direction": t["direction"],
            "to_vpa": t["beneficiary_vpa"],
            "to_name": (self.resolve(t["beneficiary_vpa"]) or {}).get("name", "?"),
            "initiated_at": t["initiated_at"],
            "app_err_msg": t["app_err_msg"],
            "rrn": rrn["rrn"] if rrn else None,
            "debit_ts": debit["debit_ts"] if debit else None,
            "reversal_initiated_at": debit["reversal_initiated_at"] if debit else None,
            "reversal_credited_at": debit["reversal_credited_at"] if debit else None,
            "fail_code": code,
            "is_demo_case": bool(t["is_demo_case"]),
        }

    def history(self, user_id, limit=40):
        rows = self.db.execute(
            "SELECT txn_id, status, amount_paise, beneficiary_vpa, initiated_at, "
            "direction, COALESCE(entry_type,'debit') AS entry_type "
            "FROM paytm_txn WHERE user_id=? AND is_demo_case=0 "
            "ORDER BY initiated_at DESC LIMIT ?", (user_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(zip(r.keys(), r))
            nm = (self.resolve(r["beneficiary_vpa"]) or {}).get("name", r["beneficiary_vpa"])
            d["to_name"] = nm
            out.append(d)
        return out

    def balance_paise(self, user_id):
        """Balance = opening + wallet ledger. Every real money movement since
        the opening is one ledger row, so balances are per-user and correct
        for internal transfers too (the beneficiary's side is a payin)."""
        delta = self.db.execute(
            "SELECT COALESCE(SUM(delta_paise),0) s FROM wallet_ledger WHERE user_id=?",
            (user_id,)).fetchone()["s"]
        return 1_850_000 + delta                # opening ≈ ₹18,500 each


_PENDING = {}   # txn_id -> (decision, at, amount, vpa, direction)
_DONE = {}
_BALANCE_ANCHOR = {}
