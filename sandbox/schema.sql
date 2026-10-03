-- Sahayak v2 sandbox schema — the 5 log tables + 3 supporting tables.
-- Column names are the contract defined on data-protocol.html.
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    kyc_tier       TEXT NOT NULL,            -- MIN | FULL
    preferred_lang TEXT NOT NULL,            -- hi | en | te
    home_city      TEXT,
    device_id      TEXT,
    signup_days    INTEGER,
    mobile         TEXT,
    login_pin      TEXT
);

CREATE TABLE IF NOT EXISTS paytm_txn (
    txn_id          INTEGER PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    direction       TEXT NOT NULL,           -- P2P | P2M
    amount_paise    INTEGER NOT NULL,
    remitter_vpa    TEXT NOT NULL,
    beneficiary_vpa TEXT NOT NULL,
    initiated_at    TEXT NOT NULL,           -- ISO8601 local
    status          TEXT NOT NULL,           -- SUCCESS | PENDING | FAILURE
    app_err_msg     TEXT,
    device_id       TEXT,
    is_demo_case    INTEGER DEFAULT 0,       -- the 3 authored demo cases
    entry_type      TEXT DEFAULT 'debit'     -- debit | credit (money received)
);

CREATE TABLE IF NOT EXISTS psp_gateway_log (
    psp_ref    INTEGER PRIMARY KEY,
    txn_id     INTEGER NOT NULL REFERENCES paytm_txn(txn_id),
    req_rcvd_at TEXT,
    resp_at    TEXT,
    resp_code  TEXT,
    forwarded  INTEGER NOT NULL DEFAULT 1    -- 0 = died at gateway
);

CREATE TABLE IF NOT EXISTS npci_switch_log (
    rrn           TEXT PRIMARY KEY,          -- 12-digit master key
    txn_id        INTEGER NOT NULL REFERENCES paytm_txn(txn_id),
    leg           TEXT NOT NULL,             -- PSP_TO_NPCI | NPCI_TO_BEN
    resp_code     TEXT,
    leg_ts        TEXT,
    expiry_attempted INTEGER NOT NULL DEFAULT 0,
    settlement_batch_id TEXT
);

CREATE TABLE IF NOT EXISTS remitter_bank_ledger (
    rrn                    TEXT PRIMARY KEY REFERENCES npci_switch_log(rrn),
    debit_ts               TEXT,             -- NULL = never debited
    debit_amount_paise     INTEGER,
    reversal_initiated_at  TEXT,
    reversal_credited_at   TEXT,
    hold_flag              INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS beneficiary_bank_ledger (
    rrn                TEXT PRIMARY KEY REFERENCES npci_switch_log(rrn),
    credit_ts          TEXT,
    credit_status      TEXT,                 -- CREDITED | FAILED | BLOCKED
    fail_reason        TEXT,                 -- technical | account | limit
    account_status     TEXT NOT NULL,        -- ACTIVE | FROZEN | KYC_LAPSED
    fraud_reports_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS txn_history_stats (
    user_id                   TEXT NOT NULL,
    beneficiary_vpa           TEXT NOT NULL,
    first_time_beneficiary    INTEGER NOT NULL,
    txns_with_this_beneficiary INTEGER NOT NULL,
    avg_amount_30d_paise      INTEGER NOT NULL,
    max_amount_90d_paise      INTEGER NOT NULL,
    PRIMARY KEY (user_id, beneficiary_vpa)
);

CREATE TABLE IF NOT EXISTS complaints (
    complaint_id  TEXT PRIMARY KEY,          -- CMP-XXXXXX
    rrn           TEXT NOT NULL,
    filed_at      TEXT,
    channel       TEXT NOT NULL,             -- agent | helpline | portal
    type          TEXT NOT NULL,             -- stuck | dispute
    status        TEXT NOT NULL,             -- OPEN | RESOLVED
    sla_due_at    TEXT,
    escalated_to  TEXT
);

CREATE INDEX IF NOT EXISTS idx_txn_user    ON paytm_txn(user_id, initiated_at);
CREATE INDEX IF NOT EXISTS idx_txn_status  ON paytm_txn(status, initiated_at);
CREATE INDEX IF NOT EXISTS idx_npci_txn    ON npci_switch_log(txn_id);
CREATE INDEX IF NOT EXISTS idx_remit_rrn   ON remitter_bank_ledger(rrn);

CREATE TABLE IF NOT EXISTS wallet_ledger (
    entry_id   INTEGER PRIMARY KEY,
    user_id    TEXT NOT NULL,
    txn_id     INTEGER,
    delta_paise INTEGER NOT NULL,
    kind       TEXT NOT NULL,                -- payout | payin
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_ledger(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet ON wallet_ledger(user_id, txn_id, kind);
