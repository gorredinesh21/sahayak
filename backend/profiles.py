#!/usr/bin/env python3
"""Seed the 4 demo profiles (A/B/C/D) for the SaaS dashboard.
Adds to the existing sandbox without touching the 1.2M history."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from pay import PayEngine, MERCHANT_DISPLAY  # noqa: E402

DB = os.environ.get("SAHAYAK_DB",
                    os.path.join(os.path.dirname(__file__), "..", "sandbox", "sahayak.db"))
NOW = datetime.now()
PROFILES = []


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class PSeeder:
    """Direct writer for hand-crafted profile cases."""
    def __init__(self, db):
        self.db = db
        self.db.row_factory = sqlite3.Row
        txn_max = (self.db.execute("SELECT MAX(txn_id) m FROM paytm_txn")
                   .fetchone()["m"] or 0)
        psp_max = (self.db.execute("SELECT MAX(psp_ref) m FROM psp_gateway_log")
                   .fetchone()["m"] or 0)
        self.next_txn = max(txn_max, psp_max) + 1000
        self.rrn_n = self.db.execute("SELECT COUNT(*) c FROM npci_switch_log").fetchone()["c"]

    def user(self, uid, name, mobile, device, lang="en"):
        self.db.execute(
            "INSERT OR REPLACE INTO users (user_id,name,kyc_tier,preferred_lang,"
            "home_city,state,device_id,signup_days,mobile,login_pin,psp_bank,"
            "payer_bank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, name, "FULL", lang, "Mumbai", "Maharashtra", device, 400,
             mobile, mobile[-4:], "Paytm (HDFC PSP)", "HDFC Bank"))
        # some ordinary history so stats/risk features are real
        for i in range(30):
            at = NOW - timedelta(hours=random.uniform(24, 2000))
            ben = random.choice([m for m in MERCHANT_DISPLAY
                                 if "quickloan" not in m])
            amt = random.randint(10000, 400000)
            t = self.txn()
            self.db.execute(
                "INSERT INTO paytm_txn (txn_id,user_id,direction,amount_paise,remitter_vpa,"
                "beneficiary_vpa,initiated_at,status,app_err_msg,device_id,is_demo_case,"
                "entry_type) VALUES (?,?,?,?,?,?,?,?,?,?,0,'debit')",
                (t, uid, "P2M", amt, f"{uid}@paytm", ben, iso(at), "SUCCESS",
                 None, device))
            self.rrn_n += 1
            rrn = f"{at.month:02d}{at.day:02d}{self.rrn_n % 100000000:08d}"
            self.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                            (rrn, t, "PSP_TO_NPCI", "00", iso(at), 0, None))
            self.db.execute("INSERT INTO remitter_bank_ledger VALUES (?,?,?,?,?,?)",
                            (rrn, iso(at), amt, None, None, 0))
            self.rrn_n += 1
            r2 = f"{at.month:02d}{at.day:02d}{self.rrn_n % 100000000:08d}"
            self.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                            (r2, t, "NPCI_TO_BEN", "00", iso(at), 0,
                             "SETTLE-" + at.strftime("%Y%m%d")))
            self.db.execute("INSERT INTO beneficiary_bank_ledger VALUES (?,?,?,?,?,?)",
                            (r2, iso(at), "CREDITED", None, "ACTIVE", 0))

    def txn(self):
        self.next_txn += 1
        return self.next_txn


import random  # noqa: E402
random.seed(777)


def legs(p, txn, at, debit=None, credit=None, expiry=False, psp_code=None):
    p.db.execute("INSERT INTO psp_gateway_log VALUES (?,?,?,?,?,?)",
                 (txn, txn, iso(at), iso(at + timedelta(milliseconds=(30000 if psp_code is None
                  and expiry else 420))), psp_code, 0 if psp_code else 1))
    p.rrn_n += 1
    rrn = f"{at.month:02d}{at.day:02d}{p.rrn_n % 100000000:08d}"
    if debit is not None:
        p.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                     (rrn, txn, "PSP_TO_NPCI", "00", iso(at + timedelta(seconds=1)),
                      1 if expiry else 0, None))
        p.db.execute("INSERT INTO remitter_bank_ledger VALUES (?,?,?,?,?,?)",
                     (rrn, iso(at + timedelta(seconds=1)), debit,
                      None, None, 0))
    else:
        p.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                     (rrn, txn, "PSP_TO_NPCI", None, iso(at), 1 if expiry else 0, None))
    if credit is not None:
        p.rrn_n += 1
        r2 = f"{at.month:02d}{at.day:02d}{p.rrn_n % 100000000:08d}"
        code, status, reason, acct, reports = credit
        p.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                     (r2, txn, "NPCI_TO_BEN", code, iso(at + timedelta(seconds=3)), 0,
                      "SETTLE-" + at.strftime("%Y%m%d") if status == "CREDITED" else None))
        p.db.execute("INSERT INTO beneficiary_bank_ledger VALUES (?,?,?,?,?,?)",
                     (r2, iso(at + timedelta(seconds=3)) if status == "CREDITED" else None,
                      status, reason, acct, reports))
    return rrn


def profile_row(p, tag, uid, txn, at, status, err):
    p.db.execute(
        "INSERT INTO paytm_txn (txn_id,user_id,direction,amount_paise,remitter_vpa,"
        "beneficiary_vpa,initiated_at,status,app_err_msg,device_id,is_demo_case,"
        "entry_type) VALUES (?,?,?,?,?,?,?,?,?,?,2,'debit')",
        (txn, uid, "P2M", PROFILES_AMOUNTS[txn], f"{uid}@paytm", PROFILES_BEN[txn],
         iso(at), status, err, PROFILES_DEV[txn]))
    PROFILES.append({"tag": tag, "txn_id": txn, "user_id": uid})


def main():
    db = sqlite3.connect(DB)
    db.execute("PRAGMA busy_timeout=8000")
    for tbl in ("paytm_txn", "txn_history_stats", "wallet_ledger"):
        db.execute(f"DELETE FROM {tbl} WHERE user_id LIKE '%.profile'")
    db.execute("DELETE FROM users WHERE user_id LIKE '%.profile'")
    # orphan rails from earlier profile runs (txn rows already gone)
    db.execute("""DELETE FROM psp_gateway_log WHERE txn_id NOT IN
                  (SELECT txn_id FROM paytm_txn)""")
    db.execute("""DELETE FROM npci_switch_log WHERE txn_id NOT IN
                  (SELECT txn_id FROM paytm_txn)""")
    db.execute("""DELETE FROM remitter_bank_ledger WHERE rrn NOT IN
                  (SELECT rrn FROM npci_switch_log)""")
    db.execute("""DELETE FROM beneficiary_bank_ledger WHERE rrn NOT IN
                  (SELECT rrn FROM npci_switch_log)""")
    db.commit()
    p = PSeeder(db)

    global PROFILES_AMOUNTS, PROFILES_BEN, PROFILES_DEV
    # ---- customers
    p.user("arjun.profile", "Arjun Mehta", "9900000011", "dev_arjun_a")
    p.user("bhavya.profile", "Bhavya Rao", "9900000022", "dev_bhavya_b")
    p.user("chitra.profile", "Chitra Iyer", "9900000033", "dev_chitra_c")
    p.user("dev.profile", "Dev Malhotra", "9900000044", "dev_dev_d")

    # demo hero — the login the phone app uses
    p.user("dinesh.demo", "Dinesh Gorre", "9848012345", "dev_dinesh_01", "hi")
    for i in range(40):
        at = NOW - timedelta(hours=random.uniform(4, 2100))
        ben = random.choice([m for m in MERCHANT_DISPLAY if "quickloan" not in m])
        amt = random.randint(10000, 400000)
        t0 = p.txn()
        p.db.execute(
            "INSERT INTO paytm_txn (txn_id,user_id,direction,amount_paise,"
            "remitter_vpa,beneficiary_vpa,initiated_at,status,app_err_msg,"
            "device_id,is_demo_case,entry_type) VALUES (?,?,?,?,?,?,?,?,?,?,0,'debit')",
            (t0, "dinesh.demo", "P2M", amt, "dinesh.demo@paytm", ben, iso(at),
             "SUCCESS", None, "dev_dinesh_01"))
        p.rrn_n += 1
        r0 = f"{at.month:02d}{at.day:02d}{p.rrn_n % 100000000:08d}"
        p.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                     (r0, t0, "PSP_TO_NPCI", "00", iso(at), 0, None))
        p.db.execute("INSERT INTO remitter_bank_ledger VALUES (?,?,?,?,?,?)",
                     (r0, iso(at), amt, None, None, 0))
        p.rrn_n += 1
        r1 = f"{at.month:02d}{at.day:02d}{p.rrn_n % 100000000:08d}"
        p.db.execute("INSERT INTO npci_switch_log VALUES (?,?,?,?,?,?,?)",
                     (r1, t0, "NPCI_TO_BEN", "00", iso(at), 0,
                      "SETTLE-" + at.strftime("%Y%m%d")))
        p.db.execute("INSERT INTO beneficiary_bank_ledger VALUES (?,?,?,?,?,?)",
                     (r1, iso(at), "CREDITED", None, "ACTIVE", 0))

    # hero demo contacts (deterministic, diverse, 3 with payment history)
    import json as _json
    pool = [r[0] for r in p.db.execute(
        "SELECT user_id FROM users WHERE home_city='Mumbai' AND user_id NOT"
        " LIKE '%.profile' ORDER BY user_id LIMIT 200").fetchall()] if False else [
        r[0] for r in p.db.execute(
            "SELECT user_id FROM users WHERE home_city='Mumbai'"
            " AND user_id NOT LIKE '%.profile'").fetchall()]
    random.Random(123).shuffle(pool)
    seen, picks = set(), []
    for uid in pool:
        f = uid.split(".")[0]
        if f in seen:
            continue
        seen.add(f); picks.append(uid)
        if len(picks) == 12:
            break
    for i, c in enumerate(picks):
        p.db.execute("INSERT OR REPLACE INTO contacts VALUES (?,?,?,?,1)",
                     ("dinesh.demo", c, [4, 2, 7][i] if i < 3 else 0,
                      "2026-09-2%dT1%d:00:00" % (i + 1, i) if i < 3 else None))
    p.db.commit()
    LOOKALIKE_SOURCE = picks[1] if len(picks) > 1 else None

    t = p.txn()
    PROFILES_AMOUNTS = {}
    PROFILES_BEN = {}
    PROFILES_DEV = {}

    # ---------- PROFILE A — failed at a specific stage: gateway switch timeout
    tA = t
    PROFILES_AMOUNTS[tA], PROFILES_BEN[tA], PROFILES_DEV[tA] = \
        74900, "electronics@okaxis", "dev_arjun_a"
    at = NOW - timedelta(minutes=25)
    profile_row(p, "A", "arjun.profile", tA, at, "FAILURE",
                "Money debited but not credited")
    rrnA = legs(p, tA, at, debit=74900)                # debit done
    p.db.execute("UPDATE npci_switch_log SET resp_code='Z6' WHERE rrn=?", (rrnA,))
    p.db.execute("UPDATE remitter_bank_ledger SET reversal_initiated_at=? WHERE rrn=?",
                 (iso(at + timedelta(minutes=8)), rrnA))

    # ---------- PROFILE B — debited, not credited, SLA (T+1) still ACTIVE
    tB = p.txn()
    PROFILES_AMOUNTS[tB], PROFILES_BEN[tB], PROFILES_DEV[tB] = \
        185000, "store.paytm@ybl", "dev_bhavya_b"
    at = NOW - timedelta(hours=5)
    profile_row(p, "B", "bhavya.profile", tB, at, "FAILURE",
                "Money debited but not credited")
    rrn = legs(p, tB, at, debit=185000,
               credit=("Z5", "FAILED", "technical", "ACTIVE", 0))
    p.db.execute("UPDATE remitter_bank_ledger SET reversal_initiated_at=? WHERE rrn=?",
                 (iso(at + timedelta(minutes=10)), rrn))

    # ---------- PROFILE C — debited, not credited, SLA EXPIRED
    tC = p.txn()
    PROFILES_AMOUNTS[tC], PROFILES_BEN[tC], PROFILES_DEV[tC] = \
        42000, "kirana@oksbi", "dev_chitra_c"
    at = NOW - timedelta(hours=40)
    profile_row(p, "C", "chitra.profile", tC, at, "PENDING", "Payment processing")
    legs(p, tC, at, debit=42000, expiry=True)          # 40h pending — rails gave up

    # ---------- PROFILE D — suspicious SUCCESS (fraud signals, new device, night)
    tD = p.txn()
    PROFILES_AMOUNTS[tD], PROFILES_BEN[tD], PROFILES_DEV[tD] = \
        1450000, "quickloan.help@ybl", "dev_dev_d_NEW"
    at = (NOW - timedelta(hours=2)).replace(hour=2, minute=14)
    profile_row(p, "D", "dev.profile", tD, at, "SUCCESS", None)
    legs(p, tD, at, debit=1450000,
         credit=("00", "CREDITED", None, "ACTIVE", 14))

    db.execute("DELETE FROM txn_history_stats WHERE user_id LIKE '%.profile'")
    db.commit()

    # rebuild stats for the four customers (SQL, same as seeder)
    from seed_stats import build  # tiny helper below
    build(db, [u[0] for u in db.execute(
        "SELECT user_id FROM users WHERE user_id LIKE '%.profile'"
        " OR user_id='dinesh.demo'")])

    for pr in PROFILES:
        print(f"profile {pr['tag']}: txn#{pr['txn_id']} customer={pr['user_id']}")
    print(f"seeded → {DB}")


if __name__ == "__main__":
    import seed_stats  # noqa: F401  (created by this script's companion)
    main()
