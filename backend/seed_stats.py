"""Tiny helper: rebuild txn_history_stats for specific users (SQL, fast)."""
from datetime import datetime, timedelta


def build(db, user_ids):
    c30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    for uid in user_ids:
        db.execute("DELETE FROM txn_history_stats WHERE user_id=?", (uid,))
        rows = db.execute(
            """SELECT beneficiary_vpa, COUNT(*) cnt, MAX(amount_paise) mx,
                      MAX(initiated_at) latest
               FROM paytm_txn WHERE user_id=? GROUP BY 1""", (uid,)).fetchall()
        avg30 = db.execute(
            "SELECT CAST(AVG(amount_paise) AS INTEGER) FROM paytm_txn "
            "WHERE user_id=? AND initiated_at>=?", (uid, c30)).fetchone()[0] or 100000
        for r in rows:
            prior = db.execute(
                "SELECT COUNT(*) FROM paytm_txn WHERE user_id=? AND beneficiary_vpa=? "
                "AND initiated_at < ?", (uid, r["beneficiary_vpa"], r["latest"])
            ).fetchone()[0]
            db.execute(
                "INSERT INTO txn_history_stats VALUES (?,?,?,?,?,?)",
                (uid, r["beneficiary_vpa"], 1 if prior == 0 else 0, prior,
                 avg30, r["mx"]))
    db.commit()
