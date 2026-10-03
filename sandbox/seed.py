#!/usr/bin/env python3
"""
Sahayak v2 sandbox seeder — SCALE build (realistic, millions-capable).

Real-data reality (researched 2026-10-01): per-transaction UPI logs are not
public anywhere (RBI privacy). This generator is calibrated to everything that
IS public — NPCI per-bank TD rates, official code semantics, system-wide mix —
plus behavioural realism so the data doesn't read as dummy:

  * proper Indian first+last names → user ids and P2P VPAs (arjun.sharma12@paytm)
  * social graph: each user pays a small set of regular contacts (Zipf), not
    random strangers → first_time_beneficiary flags occur naturally
  * Zipf-weighted merchants (kirana/store >> laundry)
  * time patterns: diurnal curve, weekends +30%, salary days (1-5) +25%,
    festival days +60%, month-end insufficient-funds clustering
  * amounts: direction-specific lognormal + round-number snapping (₹100/₹500/
    ₹1,000 spikes — real humans pay round numbers)
  * peak-hour (8-10 pm) technical-decline ×1.3 — banks strain under load
  * RRN = MMDD + 8 digits (real UPI RRNs encode the date)
  * fraud-VPA corner with report counts and frozen accounts

Plus the authored layer: demo user + 3 demo cases (A/B/C) + closed look-alikes
for Cognee memory. Same schema & contracts as before.

Usage:
  python3 seed.py [db_path] [--users N] [--per-user M] [--months K] [--quick]
  defaults: 3000 users × 400 txns ≈ 1.2M transactions over 6 months
  --quick : 300×100 ≈ 30k (fast smoke build)
"""
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta

random.seed(4102155)  # RRN-of-the-demo-case seed → reproducible builds

DB_PATH_DEFAULT = os.path.join(os.path.dirname(__file__), "sahayak.db")

# ---------------------------------------------------------------- calibration
BANK_TD = {  # per-bank technical-decline probability (public NPCI FY25 data)
    "@okhdfcbank": 0.0008, "@okicici": 0.0020, "@okkotak": 0.0030,
    "@okaxis": 0.0040, "@oksbi": 0.0060, "@okybl": 0.0100,
    "@okpnbsk": 0.0120, "@bandhan": 0.0250, "@jio": 0.0720, "@airtel": 0.0730,
}
BD_RATE = 0.093
TD_CODE_MIX = {"Z5": 0.45, "Z8": 0.05, "T1": 0.25, "Z6": 0.15, "U50": 0.10}
BD_CODE_MIX = {"U30": 0.55, "Z9": 0.20, "Z2": 0.15, "U16": 0.10}
REVERSAL_HOURS = {"Z5": (6, 40), "Z8": (6, 48), "T1": (2, 30), "U50": (2, 24), "Z6": (1, 12)}
SLA_MINUTES = 30

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
MERCHANTS = {  # Zipf-ish popularity
    "store.paytm@ybl": 100, "kirana@oksbi": 92, "swiggy.pay@okhdfcbank": 80,
    "amazonpay@okaxis": 76, "zomato.pay@okhdfcbank": 70, "bigbazaar@okybl": 55,
    "medplus@okicici": 48, "irctc.rail@okicici": 46, "petrol.pump@okaxis": 44,
    "electricbill@oksbi": 40, "dmart@okkotak": 38, "uber.pay@okhdfcbank": 36,
    "amazonretail@okhdfcbank": 34, "apollo.pharm@okicici": 30, "burgerking@okaxis": 28,
    "jio.recharge@jio": 26, "airtel.postpaid@airtel": 25, "tsrtcbus@okicici": 18,
    "waterbill@oksbi": 16, "decathlon.hyd@okhdfcbank": 14, "petromax@okaxis": 12,
    "campusstore@okhdfcbank": 10, "laundrywala@oksbi": 8, "studioclick@okkotak": 6,
}
MERCHANT_NAMES = list(MERCHANTS)
MERCHANT_W = list(MERCHANTS.values())
FRAUD_VPAS = {
    "quickloan.help@ybl":     {"reports": 14, "acct": "ACTIVE"},
    "kyc-update.desk@airtel":  {"reports": 27, "acct": "FROZEN"},
    "cashback-claim@jio":      {"reports": 9,  "acct": "ACTIVE"},
    "refund-desk99@okaxis":    {"reports": 31, "acct": "FROZEN"},
    "lottery.win@okybl":       {"reports": 18, "acct": "ACTIVE"},
    "verify-otp@okpnbsk":      {"reports": 22, "acct": "KYC_LAPSED"},
    "insurance-claim@jio":     {"reports": 12, "acct": "ACTIVE"},
    "fastag-rebate@okaxis":    {"reports": 8,  "acct": "ACTIVE"},
    "loan-approval@airtel":    {"reports": 35, "acct": "FROZEN"},
    "gift-card.pay@okybl":     {"reports": 11, "acct": "ACTIVE"},
    "bank-verify@okpnbsk":     {"reports": 19, "acct": "KYC_LAPSED"},
    "cash-prize@jio":          {"reports": 26, "acct": "FROZEN"},
}
FESTIVAL_DAYS = {  # (month, day) → +60% volume
    (1, 1): "New Year", (1, 14): "Sankranti", (3, 4): "Holi", (8, 15): "Indep.",
    (10, 2): "Gandhi Jayanti", (10, 20): "Dussehra", (11, 1): "Diwali",
    (11, 14): "Children's Day", (12, 25): "Christmas", (12, 31): "NYE",
}
BD_ERR = {"U30": "Incorrect UPI PIN", "Z9": "Invalid UPI ID",
          "Z2": "Insufficient balance", "U16": "Beneficiary blocked"}
PEAK_HOURS = {20, 21, 22}          # evening strain window → TD ×1.3

NOW = datetime.now()


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def hours_ago(h):
    return NOW - timedelta(hours=h)


# ---------------------------------------------------------------- time model
def draw_datetime(months):
    """A timestamp with real behavioural shape: festival > salary-day >
    weekend > weekday, then an intra-day diurnal curve."""
    for _ in range(12):
        at = NOW - timedelta(hours=random.uniform(0.2, months * 24 * 30.4))
        weight = 1.0
        if (at.month, at.day) in FESTIVAL_DAYS:
            weight *= 1.6
        if at.day <= 5:
            weight *= 1.25
        if at.weekday() >= 5:
            weight *= 1.3
        if random.random() < 0.35:                    # diurnal gate
            weight *= 0.25 if at.hour in (3, 4, 5) else 1.0
        if at.hour in (9, 10, 12, 13, 18, 19) or at.hour in PEAK_HOURS:
            weight *= 1.4
        if random.random() < min(weight, 2.2) / 2.2:
            return at
    return at


def draw_amount(direction):
    mu, sg = (6.2, 0.85) if direction == "P2P" else (6.6, 0.95)
    paise = int(round(random.lognormvariate(mu, sg), 2) * 100)
    paise = max(100, min(paise, 5_000_000))
    if random.random() < 0.34:                        # round-number clustering
        step = random.choice([10000, 50000, 100000, 200000])
        paise = max(step, round(paise / step) * step)
    elif direction == "P2M" and random.random() < 0.3:
        paise = max(1000, round(paise / 1000) * 1000)  # bills to the rupee
    return paise


def draw_rrn(at, seq):
    return f"{at.month:02d}{at.day:02d}{seq % 100000000:08d}"


# ---------------------------------------------------------------- seeder core
class Seeder:
    """Buffered writer — millions of rows via executemany."""
    FLUSH_EVERY = 20000  # txns

    def __init__(self, db):
        self.db = db
        self.buf = {t: [] for t in ("paytm_txn", "psp_gateway_log", "npci_switch_log",
                                    "remitter_bank_ledger", "beneficiary_bank_ledger",
                                    "complaints", "users")}
        self.txn_seq = 0
        self.psp_seq = 0
        self.rrn_seq = 0
        self.cmp_seq = 0
        self.pending = 0

    def flush(self, force=False):
        if not force and self.pending < self.FLUSH_EVERY:
            return
        for t, rows in self.buf.items():
            if rows:
                self.db.executemany(
                    f"INSERT INTO {t} VALUES ({','.join('?' * len(rows[0]))})", rows)
                self.buf[t] = []
        self.db.commit()
        self.pending = 0

    # -- row builders (buffered) ---------------------------------------
    def add_txn(self, user, direction, amount, ben_vpa, at, status, err=None, demo=0):
        self.txn_seq += 1
        self.buf["paytm_txn"].append(
            (self.txn_seq, user, direction, amount, f"{user}@paytm", ben_vpa,
             iso(at), status, err, f"dev_{user.split('.')[0]}", demo, "debit"))
        self.pending += 1
        return self.txn_seq

    def add_psp(self, txn_id, at, code, forwarded=1, latency_ms=None):
        self.psp_seq += 1
        lat = latency_ms or int(min(4000, random.lognormvariate(5.6, 0.7)))
        self.buf["psp_gateway_log"].append(
            (self.psp_seq, txn_id, iso(at), iso(at + timedelta(milliseconds=lat)),
             code, forwarded))

    def add_legs(self, txn_id, at, debit=None, credit=None, expiry=False):
        if debit is None and credit is None:
            self.rrn_seq += 1
            rrn = draw_rrn(at, self.rrn_seq)
            self.buf["npci_switch_log"].append(
                (rrn, txn_id, "PSP_TO_NPCI", None, iso(at), 1 if expiry else 0, None))
            return rrn
        if debit is not None:
            self.rrn_seq += 1
            rrn = draw_rrn(at, self.rrn_seq)
            ts = iso(debit.get("ts", at + timedelta(seconds=2)))
            self.buf["npci_switch_log"].append(
                (rrn, txn_id, "PSP_TO_NPCI", debit.get("code", "00"), ts, 0, None))
            self.buf["remitter_bank_ledger"].append(
                (rrn, ts, debit.get("amount"),
                 debit.get("rev_init"), debit.get("rev_credited"), debit.get("hold", 0)))
            debit_rrn = rrn
        if credit is not None:
            self.rrn_seq += 1
            rrn = draw_rrn(at, self.rrn_seq)
            ts = iso(credit.get("ts", at + timedelta(seconds=4)))
            self.buf["npci_switch_log"].append(
                (rrn, txn_id, "NPCI_TO_BEN", credit.get("code", "00"), ts,
                 1 if expiry else 0, credit.get("batch")))
            self.buf["beneficiary_bank_ledger"].append(
                (rrn, ts, credit.get("status", "CREDITED"), credit.get("fail_reason"),
                 credit.get("acct", "ACTIVE"), credit.get("reports", 0)))
        return debit_rrn if debit is not None else None

    def add_complaint(self, rrn, at, type_="stuck", status="RESOLVED", sla_h=24):
        self.cmp_seq += 1
        cid = f"CMP-{338700 + self.cmp_seq}"
        self.buf["complaints"].append(
            (cid, rrn, iso(at), "agent", type_, status,
             iso(at + timedelta(hours=sla_h)), None))
        return cid

    # -- outcome model ---------------------------------------------------
    def synth_txn(self, user, at, contacts=None):
        direction = "P2P" if random.random() < 0.62 else "P2M"
        if direction == "P2P":
            # 78% to a regular contact (Zipf), 22% to a stranger
            if contacts and random.random() < 0.78:
                ben = contacts[min(int(random.paretovariate(1.4)) - 1, len(contacts) - 1)]
            else:
                ben = random.choice(self.population_vpas)
        else:
            ben = random.choices(MERCHANT_NAMES, weights=MERCHANT_W)[0]
        amount = draw_amount(direction)
        td_prob = BANK_TD.get("@" + ben.split("@")[-1], 0.006)
        if at.hour in PEAK_HOURS:
            td_prob *= 1.3                            # banks strain at peak

        bd_rate = BD_RATE
        if (at.day >= 27 or at.day <= 2) and direction == "P2P":
            bd_rate *= 1.35                           # month-end balance crunch

        r = random.random()
        if r < td_prob:
            code = random.choices(list(TD_CODE_MIX), weights=TD_CODE_MIX.values())[0]
            self._td_case(user, direction, amount, ben, at, code)
        elif r < td_prob + bd_rate:
            mix = dict(BD_CODE_MIX)
            if (at.day >= 27 or at.day <= 2):
                mix["Z2"] *= 2.2                      # insufficient funds clusters
            code = random.choices(list(mix), weights=mix.values())[0]
            t = self.add_txn(user, direction, amount, ben, at, "FAILURE", BD_ERR[code])
            self.add_psp(t, at, code, forwarded=0)
            if code in ("Z9", "U16"):
                self.add_legs(t, at, credit={"code": code, "status": "FAILED",
                                             "fail_reason": "account",
                                             "acct": "FROZEN" if code == "U16" else "ACTIVE"})
        else:
            fraud = random.random() < 0.0009 and direction == "P2P"
            if fraud:
                ben = random.choice(list(FRAUD_VPAS))
                amount = random.randint(500000, 1900000)
                f = FRAUD_VPAS[ben]
            t = self.add_txn(user, direction, amount, ben, at, "SUCCESS")
            self.add_psp(t, at, "00")
            self.add_legs(t, at,
                          debit={"ts": at + timedelta(seconds=2), "amount": amount},
                          credit={"ts": at + timedelta(seconds=4), "status": "CREDITED",
                                  "batch": "SETTLE-" + at.strftime("%Y%m%d"),
                                  "acct": f["acct"] if fraud else "ACTIVE",
                                  "reports": f["reports"] if fraud else 0})
        self.flush()

    def _td_case(self, user, direction, amount, ben, at, code):
        age_h = (NOW - at).total_seconds() / 3600
        lo, hi = REVERSAL_HOURS[code]
        rev_hours = random.uniform(lo, hi)
        if code in ("Z5", "Z8"):
            resolved = age_h > rev_hours + 2
            t = self.add_txn(user, direction, amount, ben, at, "FAILURE",
                             "Money debited but not credited" if age_h > 6 else None)
            self.add_psp(t, at, "00")
            rrn = self.add_legs(
                t, at,
                debit={"ts": at + timedelta(seconds=2), "amount": amount,
                       "rev_init": at + timedelta(minutes=10),
                       "rev_credited": (at + timedelta(hours=rev_hours)) if resolved else None},
                credit={"code": code, "status": "FAILED",
                        "fail_reason": "technical" if code == "Z5" else "limit"})
            if not resolved and age_h > 26 and random.random() < 0.6:
                self.add_complaint(rrn, at + timedelta(hours=26))
        else:
            t = self.add_txn(user, direction, amount, ben, at, "PENDING",
                             "Payment processing" if age_h > 0.5 else None)
            self.add_psp(t, at, None, latency_ms=30000)
            debit = None
            if code in ("T1", "U50"):
                debit = {"ts": at + timedelta(seconds=2), "amount": amount}
            self.add_legs(t, at, debit=debit, expiry=age_h > 1)


# ---------------------------------------------------------------- population
def build_population(seeder, n_users, months):
    """Realistic users + a social graph of P2P contacts."""
    random.seed(4102155)
    used = set()
    people = []
    for _ in range(n_users):
        first = random.choice(FIRST)
        last = random.choice(LAST)
        uid = f"{first}.{last}{random.randint(1, 999)}".lower()
        while uid in used:
            uid = f"{first}.{last}{random.randint(1000, 99999)}".lower()
        used.add(uid)
        people.append(uid)
        n = len(used)
        mobile = f"9{100000000 + n * 3797}"
        seeder.buf["users"].append((
            uid, f"{first} {last}", random.choice(["MIN", "FULL", "FULL", "FULL"]),
            random.choice(["hi", "hi", "en", "te", "ta"]),
            random.choice(["Hyderabad", "Mumbai", "Pune", "Patna", "Bengaluru",
                           "Chennai", "Delhi", "Vijayawada", "Jaipur", "Lucknow"]),
            f"dev_{uid.split('.')[0]}{random.randint(1, 3)}",
            random.randint(60, 3000), mobile, mobile[-4:]))
    seeder.flush(force=True)
    all_vpas = [f"{p}@paytm" for p in people]
    seeder.population_vpas = all_vpas
    # contacts: 4-14 regular payees per user (rent, family, friends)
    contacts = {}
    for p in people:
        k = random.randint(4, 14)
        contacts[p] = random.sample(all_vpas, min(k, len(all_vpas)))
    return people, contacts


def build_stats_sql(db):
    """txn_history_stats in SQL — fast at millions of rows."""
    c30 = iso(NOW - timedelta(days=30))
    db.execute("""
    INSERT INTO txn_history_stats
    SELECT u.user_id, u.beneficiary_vpa,
           CASE WHEN u.cnt = 1 THEN 1 ELSE 0 END,
           u.cnt - 1,
           COALESCE(a30.avg, 100000),
           COALESCE(m90.mx, u.pairmax)
    FROM (SELECT user_id, beneficiary_vpa, COUNT(*) cnt, MAX(amount_paise) pairmax
          FROM paytm_txn GROUP BY 1, 2) u
    LEFT JOIN (SELECT user_id, CAST(AVG(amount_paise) AS INTEGER) avg
               FROM paytm_txn WHERE initiated_at >= ? GROUP BY 1) a30
           ON a30.user_id = u.user_id
    LEFT JOIN (SELECT user_id, MAX(amount_paise) mx
               FROM paytm_txn WHERE initiated_at >= ? GROUP BY 1) m90
           ON m90.user_id = u.user_id""", (c30, c30))
    db.commit()


# ---------------------------------------------------------------- demo layer
def seed_demo(seeder):
    U = "dinesh.demo"
    seeder.buf["users"].append((U, "Dinesh Gorre", "FULL", "hi", "Hyderabad",
                                "dev_dinesh_01", 940, "9848012345", "2345"))
    for _ in range(260):
        at = hours_ago(random.uniform(2, 4380))
        ben = "kirana@oksbi" if random.random() < 0.3 else (
            random.choice(MERCHANT_NAMES) if random.random() < 0.4 else
            f"{random.choice(FIRST).lower()}.{random.choice(LAST).lower()}"
            f"{random.randint(1, 999)}@{random.choice(list(BANK_TD))}")
        seeder.synth_txn(U, at)

    lookalikes = [(300, 26, "Z5", "store.paytm@ybl"), (520, 28, "Z5", "store.paytm@ybl"),
                  (700, 24, "Z5", "store.paytm@ybl"), (410, 31, "Z5", "amazonpay@okaxis"),
                  (880, 22, "Z5", "zomato.pay@okhdfcbank"), (150, 19, "Z5", "store.paytm@ybl"),
                  (260, 12, "T1", "kirana@oksbi"), (640, 30, "T1", "dmart@okkotak"),
                  (920, 9,  "Z6", "swiggy.pay@okhdfcbank"), (340, 17, "U50", "kirana@oksbi"),
                  (760, 25, "Z5", "medplus@okicici"), (1150, 20, "Z5", "store.paytm@ybl")]
    for h_ago, rev_h, code, ben in lookalikes:
        at = hours_ago(h_ago)
        amount = random.randint(80000, 400000)
        who = random.choice(seeder.population_vpas).split("@")[0]
        t = seeder.add_txn(who, "P2M", amount, ben, at, "FAILURE",
                           "Money debited but not credited")
        seeder.add_psp(t, at, "00")
        if code in ("Z5", "Z8"):
            seeder.add_legs(t, at,
                            debit={"ts": at + timedelta(seconds=2), "amount": amount,
                                   "rev_init": at + timedelta(minutes=10),
                                   "rev_credited": at + timedelta(hours=rev_h)},
                            credit={"code": code, "status": "FAILED",
                                    "fail_reason": "technical" if code == "Z5" else "limit"})
        else:
            rrn = seeder.add_legs(t, at,
                                  debit={"ts": at + timedelta(seconds=2), "amount": amount,
                                         "rev_init": at + timedelta(hours=4),
                                         "rev_credited": at + timedelta(hours=rev_h)},
                                  expiry=True)
            seeder.add_complaint(rrn, at + timedelta(hours=30))

    # MODE A — ₹2,800 Z5 at Yes Bank, reversal in flight, NOT yet landed
    at = hours_ago(5)
    t = seeder.add_txn(U, "P2M", 280000, "store.paytm@ybl", at, "FAILURE",
                       "Money debited but not credited", demo=1)
    seeder.add_psp(t, at, "00")
    seeder.add_legs(t, at,
                    debit={"ts": at + timedelta(seconds=2), "amount": 280000,
                           "rev_init": at + timedelta(minutes=10)},
                    credit={"code": "Z5", "status": "FAILED", "fail_reason": "technical"})

    # MODE B — ₹1,150 T1 at SBI, 31h pending, debit done, rails gave up
    at = hours_ago(31)
    t = seeder.add_txn(U, "P2M", 115000, "kirana@oksbi", at, "PENDING",
                       "Payment processing", demo=1)
    seeder.add_psp(t, at, None, latency_ms=30000)
    seeder.add_legs(t, at,
                    debit={"ts": at + timedelta(seconds=2), "amount": 115000},
                    expiry=True)

    # MODE C — ₹19,000 SUCCESS to first-time fraud-VPA
    at = hours_ago(1.2)
    t = seeder.add_txn(U, "P2P", 1900000, "quickloan.help@ybl", at, "SUCCESS", demo=1)
    seeder.add_psp(t, at, "00")
    seeder.add_legs(t, at,
                    debit={"ts": at + timedelta(seconds=2), "amount": 1900000},
                    credit={"ts": at + timedelta(seconds=4), "status": "CREDITED",
                            "batch": "SETTLE-" + at.strftime("%Y%m%d"),
                            "acct": "ACTIVE", "reports": 14})

    seeder.buf["complaints"].append(
        ("CMP-330145", "100100000001", iso(hours_ago(400)), "helpline",
         "stuck", "RESOLVED", iso(hours_ago(370)), "bank_ops"))
    seeder.flush(force=True)


# ---------------------------------------------------------------- main
def parse_args(argv):
    db = DB_PATH_DEFAULT
    users, per_user, months = 3000, 400, 6
    quick = False
    it = iter(argv)
    for a in it:
        if a == "--users":
            users = int(next(it))
        elif a == "--per-user":
            per_user = int(next(it))
        elif a == "--months":
            months = int(next(it))
        elif a == "--quick":
            users, per_user = 300, 100
        else:
            db = a
    return db, users, per_user, months, quick


def main():
    global NOW
    db_path, n_users, per_user, months, quick = parse_args(sys.argv[1:])
    t0 = time.time()
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    db.executescript(open(os.path.join(os.path.dirname(__file__), "schema.sql")).read())
    db.execute("PRAGMA synchronous = OFF")

    s = Seeder(db)
    people, contacts = build_population(s, n_users, months)
    print(f"population: {len(people):,} users · {per_user} txns each over {months} months")

    for i, p in enumerate(people, 1):
        for _ in range(per_user):
            s.synth_txn(p, draw_datetime(months), contacts=contacts[p])
        if i % max(1, n_users // 10) == 0:
            print(f"  … {i:,} users · {s.txn_seq:,} txns · {time.time()-t0:,.0f}s")

    seed_demo(s)
    print("building stats table (SQL) …")
    build_stats_sql(db)

    size_mb = os.path.getsize(db_path) / 1e6
    print("\n--- seeded database ---")
    for label, q in [
        ("users", "SELECT COUNT(*) FROM users"),
        ("transactions", "SELECT COUNT(*) FROM paytm_txn"),
        ("  SUCCESS", "SELECT COUNT(*) FROM paytm_txn WHERE status='SUCCESS'"),
        ("  PENDING ", "SELECT COUNT(*) FROM paytm_txn WHERE status='PENDING'"),
        ("  FAILURE ", "SELECT COUNT(*) FROM paytm_txn WHERE status='FAILURE'"),
        ("npci legs", "SELECT COUNT(*) FROM npci_switch_log"),
        ("user×beneficiary pairs", "SELECT COUNT(*) FROM txn_history_stats"),
        ("complaints", "SELECT COUNT(*) FROM complaints"),
    ]:
        print(f"{label:24s} {db.execute(q).fetchone()[0]:>12,}")
    print("\ndemo cases:")
    for row in db.execute("SELECT txn_id,status,amount_paise,beneficiary_vpa "
                          "FROM paytm_txn WHERE is_demo_case=1"):
        print(f"  txn#{row[0]}  {row[1]:8s} ₹{row[2]/100:>9,.0f}  → {row[3]}")
    print(f"\n→ {db_path}  ({size_mb:,.0f} MB, {time.time()-t0:,.0f}s)")


if __name__ == "__main__":
    main()
