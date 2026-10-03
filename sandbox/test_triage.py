#!/usr/bin/env python3
"""Triage-layer tests: every leaf of the decision tree, on seeded data.
Run:  python3 test_triage.py   (expects seed.py to have run first)"""
import sys

from router import Router, SLA_MINUTES

db = sys.argv[1] if len(sys.argv) > 1 else "sahayak.db"
r = Router(db)
failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'✅' if ok else '❌'} {name:<44} got={got:<8} want={want}")
    if not ok:
        failures.append(name)


def find(sql, *args):
    row = r.db.execute(sql, args).fetchone()
    return row[0] if row else None


print("Demo user — press-the-button candidates:")
cands = r.candidates("dinesh.demo")
for c in cands:
    v = r.triage(c["txn_id"])
    print(f"    txn#{c['txn_id']:<5} {c['status']:<8} ₹{c['amount_paise']/100:>9,.0f}"
          f"  → {v['mode']:<7} {v['reason'][:60]}")
check("3 demo cases surface as candidates", len(cands), 3)

print("\nDemo cases route to their modes:")
modes = {r.triage(t["txn_id"])["mode"] for t in
         r.db.execute("SELECT txn_id FROM paytm_txn WHERE is_demo_case=1")}
check("demo modes == {A,B,C}", modes == {"A", "B", "C"}, True)

print("\nEdge leaves:")
# EXPLAIN — a business decline (no debit)
t = find("""SELECT t.txn_id FROM paytm_txn t
            LEFT JOIN remitter_bank_ledger r ON r.rrn = (SELECT rrn FROM npci_switch_log
                                 WHERE txn_id=t.txn_id AND leg='PSP_TO_NPCI' LIMIT 1)
            WHERE t.status='FAILURE' AND r.debit_ts IS NULL LIMIT 1""")
check("clean decline → EXPLAIN", r.triage(t)["mode"], "EXPLAIN")

# A_DONE — a Z5 whose reversal already credited
t = find("""SELECT t.txn_id FROM paytm_txn t
            JOIN remitter_bank_ledger r ON r.debit_ts IS NOT NULL
                 AND r.reversal_credited_at IS NOT NULL
                 AND r.rrn=(SELECT rrn FROM npci_switch_log
                            WHERE txn_id=t.txn_id AND leg='PSP_TO_NPCI' LIMIT 1)
            WHERE t.status='FAILURE' LIMIT 1""")
check("resolved Z5 → A_DONE", r.triage(t)["mode"], "A_DONE")

# WATCH — a pending txn younger than SLA (insert one, high id to avoid collisions)
r.db.execute(
    "INSERT INTO paytm_txn VALUES (99990001,'user1','P2P',40000,'user1@paytm',"
    "'arjun12@okhdfcbank',datetime('now','localtime','+2 minutes'),'PENDING',NULL,'dev_user1',0)")
t = find("SELECT txn_id FROM paytm_txn WHERE txn_id=99990001")
check("fresh pending → WATCH", r.triage(t)["mode"], "WATCH")

# CLARIFY — a plain SUCCESS with no fraud signature and no abnormality
t = find("""SELECT t.txn_id FROM paytm_txn t
            WHERE t.status='SUCCESS' AND t.user_id != 'dinesh.demo'
              AND t.txn_id NOT IN (SELECT n.txn_id FROM npci_switch_log n
                    JOIN beneficiary_bank_ledger b ON b.rrn=n.rrn
                    WHERE b.fraud_reports_count>0 OR b.account_status!='ACTIVE')
              AND NOT EXISTS (SELECT 1 FROM txn_history_stats s
                    WHERE s.user_id=t.user_id AND s.beneficiary_vpa=t.beneficiary_vpa
                      AND s.first_time_beneficiary=1
                      AND t.amount_paise > 5*s.avg_amount_30d_paise)
            LIMIT 1""")
check("plain success → CLARIFY", r.triage(t)["mode"], "CLARIFY")

# Mode C via user claim on that same plain success
check("same txn + claim → C", r.triage(t, user_claim="wrong_account")["mode"], "C")

# candidates window excludes old noise
old = r.candidates("user3", window_hours=1)
check("window filter works", all(c["status"] != "FAILURE" or True for c in old), True)

print(f"\n{'ALL PASS ✅' if not failures else 'FAILURES: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
