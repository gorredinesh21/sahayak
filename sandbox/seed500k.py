#!/usr/bin/env python3
"""
Sahayak 500K dataset builder — the master-task data model, self-contained.

Generates ~500,000 synthetic Indian users across 20 cities/12 states with:
  - PSP vs payer-bank modelling (PSP app provider ≠ the debited bank)
  - deterministic per-user contact graphs (same-city biased, @paytm VPAs)
  - coherent P2P/P2M histories (repeat contacts, strangers, merchants)
  - calibrated failures incl. every scenario family
  - contacts / diag_events / complaint_requests tables ready

Reuses the calibration of sandbox/seed.py (NPCI-published TD rates by bank,
BD mix, round-number amounts, diurnal time patterns).

Usage:  python3 seed500k.py [db_path] [--users N] [--per-user M] [--quick]
        defaults: 500000 users × 10 txns  (~5M txns; ~20 min, ~3.5 GB)
        --quick : 5,000 × 6 (smoke build)
"""
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta

DB_PATH = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
    else os.path.join(os.path.dirname(__file__), "sahayak.db")
args = sys.argv[1:]
QUICK = "--quick" in args


def arg(name, default):
    return int(args[args.index(name) + 1]) if name in args else default


N_USERS = 5000 if QUICK else arg("--users", 500000)
PER_USER = 6 if QUICK else arg("--per-user", 10)
rng = random.Random(500001)
NOW = datetime.now()

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE users (
    user_id TEXT PRIMARY KEY, name TEXT NOT NULL, kyc_tier TEXT NOT NULL,
    preferred_lang TEXT NOT NULL, home_city TEXT, state TEXT, device_id TEXT,
    signup_days INTEGER, mobile TEXT, login_pin TEXT, psp_bank TEXT, payer_bank TEXT);
CREATE TABLE paytm_txn (
    txn_id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, direction TEXT NOT NULL,
    amount_paise INTEGER NOT NULL, remitter_vpa TEXT NOT NULL,
    beneficiary_vpa TEXT NOT NULL, initiated_at TEXT NOT NULL, status TEXT NOT NULL,
    app_err_msg TEXT, device_id TEXT, is_demo_case INTEGER DEFAULT 0,
    entry_type TEXT DEFAULT 'debit', retry_of_txn_id INTEGER);
CREATE TABLE psp_gateway_log (
    psp_ref INTEGER PRIMARY KEY, txn_id INTEGER NOT NULL, req_rcvd_at TEXT,
    resp_at TEXT, resp_code TEXT, forwarded INTEGER NOT NULL DEFAULT 1);
CREATE TABLE npci_switch_log (
    rrn TEXT PRIMARY KEY, txn_id INTEGER NOT NULL, leg TEXT NOT NULL,
    resp_code TEXT, leg_ts TEXT, expiry_attempted INTEGER NOT NULL DEFAULT 0,
    settlement_batch_id TEXT);
CREATE TABLE remitter_bank_ledger (
    rrn TEXT PRIMARY KEY, debit_ts TEXT, debit_amount_paise INTEGER,
    reversal_initiated_at TEXT, reversal_credited_at TEXT, hold_flag INTEGER DEFAULT 0);
CREATE TABLE beneficiary_bank_ledger (
    rrn TEXT PRIMARY KEY, credit_ts TEXT, credit_status TEXT, fail_reason TEXT,
    account_status TEXT NOT NULL DEFAULT 'ACTIVE', fraud_reports_count INTEGER DEFAULT 0);
CREATE TABLE txn_history_stats (
    user_id TEXT, beneficiary_vpa TEXT, first_time_beneficiary INTEGER,
    txns_with_this_beneficiary INTEGER, avg_amount_30d_paise INTEGER,
    max_amount_90d_paise INTEGER, PRIMARY KEY (user_id, beneficiary_vpa));
CREATE TABLE wallet_ledger (
    entry_id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, txn_id INTEGER,
    delta_paise INTEGER NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet ON wallet_ledger(user_id, txn_id, kind);
CREATE TABLE complaints (
    complaint_id TEXT PRIMARY KEY, rrn TEXT NOT NULL, filed_at TEXT, channel TEXT,
    type TEXT, status TEXT, sla_due_at TEXT, escalated_to TEXT);
CREATE TABLE contacts (
    user_id TEXT NOT NULL, contact_user_id TEXT NOT NULL,
    times_paid INTEGER NOT NULL DEFAULT 0, last_paid_at TEXT,
    saved INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (user_id, contact_user_id));
CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);
CREATE TABLE diag_events (
    id INTEGER PRIMARY KEY, txn_id INTEGER, case_id TEXT, ts TEXT NOT NULL,
    seq INTEGER, kind TEXT NOT NULL, actor TEXT, label TEXT NOT NULL,
    detail TEXT, status TEXT NOT NULL DEFAULT 'ok');
CREATE INDEX IF NOT EXISTS idx_diag_txn ON diag_events(txn_id, id);
CREATE TABLE support_cases (
    case_id TEXT PRIMARY KEY, txn_id INTEGER, user_id TEXT, opened_at TEXT,
    status TEXT DEFAULT 'OPEN', intent TEXT, mode TEXT, resolution TEXT);
CREATE TABLE support_messages (
    msg_id INTEGER PRIMARY KEY, case_id TEXT, role TEXT, text TEXT,
    thinking TEXT, created_at TEXT);
CREATE TABLE complaint_requests (
    complaint_id TEXT PRIMARY KEY, txn_id INTEGER NOT NULL, rrn TEXT,
    stage TEXT NOT NULL, payload_json TEXT, api_log_json TEXT, ticket_ref TEXT,
    status TEXT NOT NULL DEFAULT 'SUBMITTED', submitted_at TEXT,
    simulated INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_txn_user ON paytm_txn(user_id, initiated_at);
CREATE INDEX IF NOT EXISTS idx_txn_status ON paytm_txn(status, initiated_at);
CREATE INDEX IF NOT EXISTS idx_npci_txn ON npci_switch_log(txn_id);
CREATE INDEX IF NOT EXISTS idx_users_mobile ON users(mobile);
CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);
"""

# ------------------------------------------------------------ calibration
BANK_TD = {"@okhdfcbank": .0008, "@okicici": .0020, "@okkotak": .0030,
           "@okaxis": .0040, "@oksbi": .0060, "@okybl": .0100, "@okpnbsk": .0120,
           "@bandhan": .0250, "@jio": .0720, "@airtel": .0730}
BD_RATE = .093
TD_CODE_MIX = {"Z5": .45, "Z8": .05, "T1": .25, "Z6": .15, "U50": .10}
BD_CODE_MIX = {"U30": .55, "Z9": .20, "Z2": .15, "U16": .10}
BD_ERR = {"U30": "Incorrect UPI PIN", "Z9": "Invalid UPI ID",
          "Z2": "Insufficient balance", "U16": "Beneficiary blocked"}
REV_H = {"Z5": (6, 40), "Z8": (6, 48), "T1": (2, 30), "U50": (2, 24), "Z6": (1, 12)}
PEAK = {20, 21, 22}
FEST = {(1, 1), (1, 14), (3, 4), (8, 15), (10, 2), (10, 20), (11, 1), (11, 14),
        (12, 25), (12, 31)}

FIRST = ["Arjun", "Priya", "Rahul", "Sneha", "Vikram", "Anjali", "Kiran", "Meera",
         "Rohit", "Divya", "Sanjay", "Lakshmi", "Gopal", "Nisha", "Tarun", "Reshma",
         "Aditya", "Kavya", "Manoj", "Pooja", "Sridhar", "Harsha", "Deepa", "Naveen",
         "Ramesh", "Sunitha", "Prakash", "Jyothi", "Mahesh", "Swapna", "Venkat",
         "Anitha", "Sravan", "Padma", "Naresh", "Hema", "Kishore", "Geetha",
         "Bharat", "Sailaja", "Murali", "Vasanthi", "Praveen", "Usha", "Nagendra",
         "Snehal", "Aakash", "Isha", "Farhan", "Zoya", "Rehan", "Nikita", "Siddharth"]
LAST = ["Sharma", "Reddy", "Nair", "Patel", "Singh", "Kumar", "Rao", "Gupta",
        "Iyer", "Das", "Bose", "Chaudhary", "Yadav", "Joshi", "Mehta", "Khan",
        "Varma", "Pillai", "Menon", "Hegde", "Goud", "Babu", "Bhatt", "Chopra",
        "Malhotra", "Kapoor", "Verma", "Srivastava", "Mishra", "Tiwari", "Pandey",
        "Naik", "Kulkarni", "Deshpande", "Sahu", "Mudiraj", "Shetty", "Rathod"]
# 20 cities / 12 states, weights ≈ population-skewed
CITIES = [("Mumbai", "Maharashtra", 62), ("Delhi", "Delhi", 56),
          ("Bengaluru", "Karnataka", 46), ("Hyderabad", "Telangana", 40),
          ("Chennai", "Tamil Nadu", 36), ("Pune", "Maharashtra", 30),
          ("Kolkata", "West Bengal", 28), ("Ahmedabad", "Gujarat", 24),
          ("Jaipur", "Rajasthan", 20), ("Lucknow", "Uttar Pradesh", 20),
          ("Patna", "Bihar", 16), ("Indore", "Madhya Pradesh", 15),
          ("Vijayawada", "Andhra Pradesh", 12), ("Kochi", "Kerala", 12),
          ("Coimbatore", "Tamil Nadu", 11), ("Bhopal", "Madhya Pradesh", 11),
          ("Nagpur", "Maharashtra", 10), ("Chandigarh", "Punjab", 8),
          ("Guwahati", "Assam", 7), ("Dehradun", "Uttarakhand", 6)]
CITY_NAMES = [c[0] for c in CITIES]
CITY_W = [c[2] for c in CITIES]
STATE_OF = {c[0]: c[1] for c in CITIES}
LANG_OF = {"Maharashtra": "mr", "Delhi": "hi", "Karnataka": "kn",
           "Telangana": "te", "Tamil Nadu": "ta", "West Bengal": "bn",
           "Gujarat": "gu", "Rajasthan": "hi", "Uttar Pradesh": "hi",
           "Bihar": "hi", "Madhya Pradesh": "hi", "Andhra Pradesh": "te",
           "Kerala": "ml", "Punjab": "pa", "Assam": "as", "Uttarakhand": "hi"}
PSPS = ["Paytm (Axis PSP)", "Paytm (HDFC PSP)", "Paytm (SBI PSP)", "Paytm (YES PSP)"]
PAYER_BANKS = ["HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra Bank",
               "Punjab National Bank", "Bank of Baroda", "Canara Bank"]
MERCHANTS = {"store.paytm@ybl": 100, "kirana@oksbi": 92, "swiggy.pay@okhdfcbank": 80,
             "amazonpay@okaxis": 76, "zomato.pay@okhdfcbank": 70, "bigbazaar@okybl": 55,
             "medplus@okicici": 48, "irctc.rail@okicici": 46, "petrol.pump@okaxis": 44,
             "electricbill@oksbi": 40, "dmart@okkotak": 38, "uber.pay@okhdfcbank": 36,
             "amazonretail@okhdfcbank": 34, "apollo.pharm@okicici": 30,
             "burgerking@okaxis": 28, "jio.recharge@jio": 26, "tsrtcbus@okicici": 18,
             "waterbill@oksbi": 16, "decathlon.hyd@okhdfcbank": 14}
M_NAMES = list(MERCHANTS)
M_W = list(MERCHANTS.values())
FRAUD_VPAS = {"quickloan.help@ybl": (14, "ACTIVE"), "kyc-update.desk@airtel": (27, "FROZEN"),
              "cashback-claim@jio": (9, "ACTIVE"), "refund-desk99@okaxis": (31, "FROZEN"),
              "lottery.win@okybl": (18, "ACTIVE"), "verify-otp@okpnbsk": (22, "KYC_LAPSED"),
              "loan-approval@airtel": (35, "FROZEN"), "cash-prize@jio": (26, "FROZEN")}


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def draw_dt(months=6):
    for _ in range(10):
        at = NOW - timedelta(hours=rng.uniform(.2, months * 730))
        w = 1.0
        if (at.month, at.day) in FEST:
            w *= 1.6
        if at.day <= 5:
            w *= 1.25
        if at.weekday() >= 5:
            w *= 1.3
        if at.hour in (3, 4, 5):
            w *= .25
        if at.hour in (9, 10, 12, 13, 18, 19, 20, 21, 22):
            w *= 1.4
        if rng.random() < min(w, 2.2) / 2.2:
            return at
    return at


def draw_amt(direction):
    mu, sg = (6.2, .85) if direction == "P2P" else (6.6, .95)
    p = int(round(rng.lognormvariate(mu, sg), 2) * 100)
    p = max(100, min(p, 5_000_000))
    if rng.random() < .34:
        step = rng.choice([10000, 50000, 100000, 200000])
        p = max(step, round(p / step) * step)
    elif direction == "P2M" and rng.random() < .3:
        p = max(1000, round(p / 1000) * 1000)
    return p


def rrn_of(at, seq):
    return f"{at.month:02d}{at.day:02d}{seq % 100000000:08d}"


def main():
    t0 = time.time()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("PRAGMA synchronous=OFF")

    buf = {t: [] for t in ("users", "paytm_txn", "psp_gateway_log",
                           "npci_switch_log", "remitter_bank_ledger",
                           "beneficiary_bank_ledger", "contacts")}
    txn_seq = psp_seq = rrn_seq = 0
    pending = 0
    named_cols = {
        "paytm_txn": "(txn_id,user_id,direction,amount_paise,remitter_vpa,"
                     "beneficiary_vpa,initiated_at,status,app_err_msg,device_id,"
                     "is_demo_case,entry_type)",
    }

    def flush(force=False):
        nonlocal pending
        if not force and pending < 25000:
            return
        for t, rows in buf.items():
            if rows:
                cols = named_cols.get(t, "")
                db.executemany(f"INSERT INTO {t} {cols} VALUES "
                               f"({','.join('?' * len(rows[0]))})", rows)
                buf[t] = []
        db.commit()
        pending = 0

    def add_txn(user, direction, amount, ben, at, status, err=None, demo=0):
        nonlocal txn_seq, pending
        txn_seq += 1
        pending += 1
        buf["paytm_txn"].append((txn_seq, user, direction, amount,
                                 f"{user}@paytm", ben, iso(at), status, err,
                                 f"dev_{user.split('.')[0]}", demo, "debit"))
        return txn_seq

    def add_psp(txn, at, code=None, fwd=1, ms=None):
        nonlocal psp_seq
        psp_seq += 1
        buf["psp_gateway_log"].append((psp_seq, txn, iso(at),
                                       iso(at + timedelta(milliseconds=ms or 420)),
                                       code, fwd))

    def legs(txn, at, debit=None, credit=None, expiry=False):
        nonlocal rrn_seq
        if debit is None and credit is None:
            rrn_seq += 1
            r = rrn_of(at, rrn_seq)
            buf["npci_switch_log"].append((r, txn, "PSP_TO_NPCI", None, iso(at),
                                           1 if expiry else 0, None))
            return r
        drrn = None
        if debit is not None:
            rrn_seq += 1
            drrn = rrn_of(at, rrn_seq)
            ts = iso(debit.get("ts", at + timedelta(seconds=2)))
            buf["npci_switch_log"].append((drrn, txn, "PSP_TO_NPCI",
                                           debit.get("code", "00"), ts, 0, None))
            buf["remitter_bank_ledger"].append((drrn, ts, debit.get("amount"),
                                                debit.get("rev_init"),
                                                debit.get("rev_credited"), 0))
        if credit is not None:
            rrn_seq += 1
            crrn = rrn_of(at, rrn_seq)
            ts = iso(credit.get("ts", at + timedelta(seconds=4)))
            buf["npci_switch_log"].append((crrn, txn, "NPCI_TO_BEN",
                                           credit.get("code", "00"), ts,
                                           1 if expiry else 0,
                                           credit.get("batch")))
            buf["beneficiary_bank_ledger"].append(
                (crrn, ts if credit.get("status") != "FAILED" else None,
                 credit.get("status", "CREDITED"), credit.get("fail_reason"),
                 credit.get("acct", "ACTIVE"), credit.get("reports", 0)))
        return drrn

    # ---------------------------------------------------------- population
    print(f"building {N_USERS:,} users across {len(CITIES)} cities …")
    city_users = {c: [] for c in CITY_NAMES}
    mobile_seq = 910000000
    used_uids = set()
    for i in range(N_USERS):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        uid = f"{first}.{last}{rng.randint(1, 99999)}".lower()
        while uid in used_uids:
            uid = f"{first}.{last}{rng.randint(100000, 999999)}".lower()
        used_uids.add(uid)
        city = rng.choices(CITY_NAMES, weights=CITY_W)[0]
        mobile_seq += 1
        state = STATE_OF[city]
        buf["users"].append((uid, f"{first} {last}",
                             rng.choices(["MIN", "FULL"], weights=[.18, .82])[0],
                             rng.choice([LANG_OF[state], LANG_OF[state], "en"]),
                             city, state, f"dev_{first.lower()}{rng.randint(1, 3)}",
                             rng.randint(60, 3000), f"{mobile_seq}",
                             str(mobile_seq)[-4:], PSPS[hash(uid) % 4],
                             PAYER_BANKS[hash(uid[::-1]) % 8]))
        city_users[city].append(uid)
        if (i + 1) % 50000 == 0:
            print(f"  … {i + 1:,} users ({time.time() - t0:,.0f}s)")
    flush(True)

    # -------------------------------------------------------- transactions
    all_uids = [u for us in city_users.values() for u in us]

    def contacts_of(uid, city):
        r = random.Random("contacts:" + uid)
        pool = city_users[city]
        want = min(4 + r.randint(0, 10), 14, max(1, len(pool) - 1))
        return r.sample(pool, want)

    print(f"generating ~{N_USERS * PER_USER:,} transactions …")
    for i, uid in enumerate(all_uids, 1):
        urow = db.execute("SELECT home_city FROM users WHERE user_id=?",
                          (uid,)).fetchone()
        city = urow[0] if urow else "Mumbai"
        my_contacts = contacts_of(uid, city)
        my_vpas = [f"{c}@paytm" for c in my_contacts]
        for c in my_contacts:
            buf["contacts"].append((uid, c, 0, None, 1))
        for _ in range(PER_USER):
            at = draw_dt(6)
            direction = "P2P" if rng.random() < .62 else "P2M"
            if direction == "P2P":
                if my_vpas and rng.random() < .78:
                    idx = min(int(rng.paretovariate(1.4)) - 1, len(my_vpas) - 1)
                    ben = my_vpas[idx]
                else:
                    ben = f"{rng.choice(FIRST).lower()}.{rng.choice(LAST).lower()}" \
                          f"{rng.randint(1, 99999)}@{rng.choice(list(BANK_TD))}"
            else:
                ben = rng.choices(M_NAMES, weights=M_W)[0]
            amount = draw_amt(direction)
            td = BANK_TD.get("@" + ben.split("@")[-1], .006)
            if at.hour in PEAK:
                td *= 1.3
            r = rng.random()
            if r < td:                                   # technical decline
                code = rng.choices(list(TD_CODE_MIX), weights=TD_CODE_MIX.values())[0]
                lo, hi = REV_H[code]
                rev = rng.uniform(lo, hi)
                age = (NOW - at).total_seconds() / 3600
                if code in ("Z5", "Z8"):
                    done = age > rev + 2
                    t = add_txn(uid, direction, amount, ben, at, "FAILURE",
                                "Money debited but not credited" if age > 6 else None)
                    add_psp(t, at, "00")
                    legs(t, at,
                         debit={"amount": amount,
                                "rev_init": iso(at + timedelta(minutes=10)),
                                "rev_credited": iso(at + timedelta(hours=rev))
                                if done else None},
                         credit={"code": code, "status": "FAILED",
                                 "fail_reason": "technical" if code == "Z5" else "limit"})
                else:
                    t = add_txn(uid, direction, amount, ben, at, "PENDING",
                                "Payment processing" if age > .5 else None)
                    add_psp(t, at, None, ms=30000)
                    d = {"amount": amount} if code in ("T1", "U50") else None
                    legs(t, at, debit=d, expiry=age > 1)
            elif r < td + BD_RATE:                        # business decline
                mix = dict(BD_CODE_MIX)
                if at.day >= 27 or at.day <= 2:
                    mix["Z2"] *= 2.2
                code = rng.choices(list(mix), weights=mix.values())[0]
                t = add_txn(uid, direction, amount, ben, at, "FAILURE", BD_ERR[code])
                add_psp(t, at, code, fwd=0)
                if code in ("Z9", "U16"):
                    legs(t, at, credit={"code": code, "status": "FAILED",
                                        "fail_reason": "account",
                                        "acct": "FROZEN" if code == "U16" else "ACTIVE"})
            else:                                         # success
                fraud = rng.random() < .0009 and direction == "P2P"
                if fraud:
                    ben = rng.choice(list(FRAUD_VPAS))
                    amount = rng.randint(500000, 1900000)
                    rep, acct = FRAUD_VPAS[ben]
                t = add_txn(uid, direction, amount, ben, at, "SUCCESS")
                add_psp(t, at, "00")
                legs(t, at, debit={"amount": amount},
                     credit={"status": "CREDITED",
                             "batch": "SETTLE-" + at.strftime("%Y%m%d"),
                             "acct": acct if fraud else "ACTIVE",
                             "reports": rep if fraud else 0})
        flush()
        if i % max(1, N_USERS // 10) == 0:
            print(f"  … {i:,} users · {txn_seq:,} txns ({time.time() - t0:,.0f}s)")
    flush(True)

    # counts for contacts from actual history (internal @paytm transfers)
    print("aggregating contact payment counts …")
    db.execute("""INSERT INTO contacts (user_id, contact_user_id, times_paid, last_paid_at, saved)
                  SELECT t.user_id, REPLACE(t.beneficiary_vpa,'@paytm',''),
                         COUNT(*), MAX(t.initiated_at), 0
                  FROM paytm_txn t
                  WHERE t.beneficiary_vpa LIKE '%@paytm'
                    AND EXISTS (SELECT 1 FROM users u WHERE u.user_id = REPLACE(t.beneficiary_vpa,'@paytm',''))
                  GROUP BY 1, 2
                  ON CONFLICT (user_id, contact_user_id)
                  DO UPDATE SET times_paid = excluded.times_paid,
                                last_paid_at = excluded.last_paid_at""")
    db.commit()

    print("building txn_history_stats …")
    c30 = iso(NOW - timedelta(days=30))
    db.execute("""
    INSERT INTO txn_history_stats
    SELECT u.user_id, u.beneficiary_vpa,
           CASE WHEN u.cnt = 1 THEN 1 ELSE 0 END, u.cnt - 1,
           COALESCE(a30.avg, 100000), COALESCE(m90.mx, u.pairmax)
    FROM (SELECT user_id, beneficiary_vpa, COUNT(*) cnt, MAX(amount_paise) pairmax
          FROM paytm_txn GROUP BY 1, 2) u
    LEFT JOIN (SELECT user_id, CAST(AVG(amount_paise) AS INTEGER) avg
               FROM paytm_txn WHERE initiated_at >= ? GROUP BY 1) a30 ON a30.user_id = u.user_id
    LEFT JOIN (SELECT user_id, MAX(amount_paise) mx
               FROM paytm_txn WHERE initiated_at >= ? GROUP BY 1) m90 ON m90.user_id = u.user_id
    """, (c30, c30))
    db.commit()

    size = os.path.getsize(DB_PATH) / 1e9
    print("\n--- dataset summary ---")
    for label, q in [("users", "SELECT COUNT(*) FROM users"),
                     ("transactions", "SELECT COUNT(*) FROM paytm_txn"),
                     ("  SUCCESS", "SELECT COUNT(*) FROM paytm_txn WHERE status='SUCCESS'"),
                     ("  PENDING", "SELECT COUNT(*) FROM paytm_txn WHERE status='PENDING'"),
                     ("  FAILURE", "SELECT COUNT(*) FROM paytm_txn WHERE status='FAILURE'"),
                     ("contact edges", "SELECT COUNT(*) FROM contacts"),
                     ("cities", "SELECT COUNT(DISTINCT home_city) FROM users")]:
        print(f"{label:14s} {db.execute(q).fetchone()[0]:>12,}")
    print(f"\n→ {DB_PATH}  ({size:,.1f} GB, {time.time() - t0:,.0f}s)")


if __name__ == "__main__":
    main()
