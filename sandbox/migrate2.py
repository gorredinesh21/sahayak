#!/usr/bin/env python3
"""Sahayak data-model v2 migration (idempotent).

Adds the modeling the master task requires:
- users: state (region), psp_bank (PSP/app provider), payer_bank (debited bank)
- contacts: persistent user-to-user payment relationships (searchable)
- diag_events: the visualizer's event stream (persisted, replayable)
- complaint_requests: realistic complaint workflow records (simulated API)
- paytm_txn.retry_of_txn_id: retry linkage for duplicate prevention
"""
import os
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "sahayak.db")
db = sqlite3.connect(DB)


def cols(table):
    return [r[1] for r in db.execute(f"PRAGMA table_info({table})")]


u = cols("users")
if "state" not in u:
    db.execute("ALTER TABLE users ADD COLUMN state TEXT")
if "psp_bank" not in u:
    db.execute("ALTER TABLE users ADD COLUMN psp_bank TEXT")
if "payer_bank" not in u:
    db.execute("ALTER TABLE users ADD COLUMN payer_bank TEXT")

t = cols("paytm_txn")
if "retry_of_txn_id" not in t:
    db.execute("ALTER TABLE paytm_txn ADD COLUMN retry_of_txn_id INTEGER")

db.executescript("""
CREATE TABLE IF NOT EXISTS contacts (
    user_id        TEXT NOT NULL,
    contact_user_id TEXT NOT NULL,
    times_paid     INTEGER NOT NULL DEFAULT 0,
    last_paid_at   TEXT,
    saved          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, contact_user_id)
);
CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);

CREATE TABLE IF NOT EXISTS diag_events (
    id      INTEGER PRIMARY KEY,
    txn_id  INTEGER,
    case_id TEXT,
    ts      TEXT NOT NULL,
    seq     INTEGER,
    kind    TEXT NOT NULL,   -- user_action|psp|npci|payer_bank|receiver_bank|
                             -- backend|db|memory|ai|tool|complaint|recovery
    actor   TEXT,
    label   TEXT NOT NULL,
    detail  TEXT,
    status  TEXT NOT NULL DEFAULT 'ok'   -- ok|fail|pending|warn
);
CREATE INDEX IF NOT EXISTS idx_diag_txn ON diag_events(txn_id, id);

CREATE TABLE IF NOT EXISTS complaint_requests (
    complaint_id  TEXT PRIMARY KEY,
    txn_id        INTEGER NOT NULL,
    rrn           TEXT,
    stage         TEXT NOT NULL,   -- VALIDATED|BUILT|SUBMITTED|ACKED|FAILED
    payload_json  TEXT,
    api_log_json  TEXT,
    ticket_ref    TEXT,
    status        TEXT NOT NULL DEFAULT 'SUBMITTED',  -- ACCEPTED|UNDER_REVIEW|RESOLVED
    submitted_at  TEXT,
    simulated     INTEGER NOT NULL DEFAULT 1
);
""")

# backfill psp/payer banks for existing users deterministically
PSPS = ["Paytm (Axis PSP)", "Paytm (HDFC PSP)", "Paytm (SBI PSP)", "Paytm (YES PSP)"]
BANKS = ["HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra Bank",
         "Punjab National Bank", "Bank of Baroda", "Canara Bank"]
STATES = {"Hyderabad": "Telangana", "Mumbai": "Maharashtra", "Pune": "Maharashtra",
          "Patna": "Bihar", "Bengaluru": "Karnataka", "Chennai": "Tamil Nadu",
          "Delhi": "Delhi", "Vijayawada": "Andhra Pradesh", "Jaipur": "Rajasthan",
          "Lucknow": "Uttar Pradesh", "Kolkata": "West Bengal", "Indore": "Madhya Pradesh"}
rows = db.execute("SELECT user_id, home_city FROM users").fetchall()
for uid, city in rows:
    db.execute("UPDATE users SET state=?, psp_bank=?, payer_bank=? WHERE user_id=?",
               (STATES.get(city or "Hyderabad", "Telangana"),
                PSPS[hash(uid) % 4], BANKS[hash(uid[::-1]) % 8], uid))
db.commit()
print(f"migrated: {len(rows)} users enriched; contacts/diag_events/"
      "complaint_requests ready; retry linkage added")
