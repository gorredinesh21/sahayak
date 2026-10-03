#!/usr/bin/env python3
"""One-time migration: adds auth columns + wallet ledger to an existing sandbox DB.
(Kept idempotent; fresh builds get these via schema.sql.)"""
import os
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "sahayak.db")
db = sqlite3.connect(DB)

cols = [r[1] for r in db.execute("PRAGMA table_info(users)")]
if "mobile" not in cols:
    db.execute("ALTER TABLE users ADD COLUMN mobile TEXT")
if "login_pin" not in cols:
    db.execute("ALTER TABLE users ADD COLUMN login_pin TEXT")

cols_t = [r[1] for r in db.execute("PRAGMA table_info(paytm_txn)")]
if "entry_type" not in cols_t:
    db.execute("ALTER TABLE paytm_txn ADD COLUMN entry_type TEXT DEFAULT 'debit'")

db.execute("""CREATE TABLE IF NOT EXISTS wallet_ledger (
    entry_id   INTEGER PRIMARY KEY,
    user_id    TEXT NOT NULL,
    txn_id     INTEGER,
    delta_paise INTEGER NOT NULL,
    kind       TEXT NOT NULL,             -- payout | payin
    created_at TEXT NOT NULL
)""")
db.execute("CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_ledger(user_id)")

# deterministic demo credentials: mobile unique per row, PIN = last 4 of mobile
db.execute("""UPDATE users SET
    mobile   = '9' || substr('000000000' || (ROWID * 3797 + 100000000), -9),
    login_pin = NULL WHERE mobile IS NULL""")
db.execute("""UPDATE users SET login_pin = substr(mobile, -4) WHERE login_pin IS NULL""")
# demo hero keeps a memorable number
db.execute("""UPDATE users SET mobile='9848012345', login_pin='2345'
              WHERE user_id='dinesh.demo'""")
db.commit()

n = db.execute("SELECT COUNT(*) FROM users WHERE mobile IS NOT NULL").fetchone()[0]
hero = db.execute("SELECT name, mobile, login_pin FROM users WHERE user_id='dinesh.demo'").fetchone()
print(f"migrated: {n} users have credentials; hero = {hero}")
