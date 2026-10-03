#!/usr/bin/env python3
"""
Sahayak memory layer — Cognee when available, SQL-grounded context as fallback.

The transactional source of truth stays in SQLite. This layer adds
contextual memory: closed support cases, conversations, similar past cases.
If the Cognee package is importable and enabled, case narratives are also
ingested into its knowledge graph for semantic recall. The rest of the app
never imports cognee directly — only this interface.
"""
import json
import os
from datetime import datetime

try:
    import asyncio
    import cognee                                    # noqa: F401
    COGNEE_IMPORTABLE = True
except Exception:
    COGNEE_IMPORTABLE = False

COGNEE_ENABLED = COGNEE_IMPORTABLE and (
    os.environ.get("SAHAYAK_COGNEE", "1") == "1")


class MemoryLayer:
    def __init__(self, db):
        self.db = db
        self.mode = "cognee+sql" if COGNEE_ENABLED else "sql-fallback"
        if COGNEE_ENABLED:
            try:  # point Cognee's brain at the same Vertex Gemini (LiteLLM-style envs)
                os.environ.setdefault("LLM_PROVIDER", "gemini")
                asyncio.get_event_loop()
            except Exception:
                pass

    # ------------------------------------------------------------ retrieval
    def customer_context(self, user_id, txn_id=None):
        """Previous support cases + conversation digests for this customer."""
        cases = self.db.execute(
            """SELECT case_id, txn_id, status, intent, opened_at, resolution
               FROM support_cases WHERE user_id=? ORDER BY opened_at DESC LIMIT 5""",
            (user_id,)).fetchall()
        out = []
        for c in cases:
            msgs = self.db.execute(
                "SELECT role, text FROM support_messages WHERE case_id=? "
                "ORDER BY msg_id DESC LIMIT 4", (c["case_id"],)).fetchall()
            out.append({
                "case_id": c["case_id"], "txn_id": c["txn_id"],
                "status": c["status"], "intent": c["intent"],
                "opened_at": c["opened_at"], "resolution": c["resolution"],
                "recent_messages": [dict(zip(m.keys(), m)) for m in reversed(msgs)],
            })
        similar = self.db.execute(
            """SELECT s.case_id, s.txn_id, s.resolution FROM support_cases s
               JOIN paytm_txn t ON t.txn_id = s.txn_id
               JOIN paytm_txn cur ON cur.txn_id = ?
               WHERE t.beneficiary_vpa = cur.beneficiary_vpa
                 AND s.case_id NOT IN (SELECT case_id FROM support_cases WHERE user_id=?)
               ORDER BY s.opened_at DESC LIMIT 3""",
            (txn_id, user_id)).fetchall() if txn_id else []
        ctx = {"customer_cases": out,
               "similar_cases_for_beneficiary": [dict(zip(s.keys(), s))
                                                 for s in similar],
               "memory_mode": self.mode}
        if COGNEE_ENABLED:
            try:
                ctx["semantic"] = self._cognee_recall(
                    f"similar past support cases and resolutions for {user_id}")
            except Exception as e:
                ctx["semantic_error"] = str(e)[:120]
        return ctx

    # -------------------------------------------------------------- ingest
    def remember_case(self, case_id):
        """Called when a case closes: narrative -> Cognee graph + SQL stays source."""
        row = self.db.execute(
            """SELECT c.*, t.amount_paise, t.beneficiary_vpa, t.status AS pay_status
               FROM support_cases c JOIN paytm_txn t ON t.txn_id=c.txn_id
               WHERE c.case_id=?""", (case_id,)).fetchone()
        if not row:
            return
        narrative = (
            f"Support case {case_id} for customer {row['user_id']}: "
            f"payment of Rs {row['amount_paise']/100:.0f} to {row['beneficiary_vpa']} "
            f"({row['pay_status']}). Intent: {row['intent'] or 'n/a'}. "
            f"Resolution: {row['resolution'] or 'conversation only'}. "
            f"Closed {datetime.now().isoformat(timespec='seconds')}.")
        self.db.execute("UPDATE support_cases SET status='CLOSED' WHERE case_id=?",
                        (case_id,))
        self.db.commit()
        if COGNEE_ENABLED:
            try:
                self._cognee_remember(narrative)
            except Exception:
                pass

    # -------------------------------------------------------------- cognee
    def _cognee_remember(self, text):
        async def run():
            await cognee.add(text)
            await cognee.cognify()
        asyncio.run(run())

    def _cognee_recall(self, query):
        async def run():
            res = await cognee.search(query_text=query)
            return "\n".join(getattr(r, "text", str(r)) for r in res[:4])
        return asyncio.run(run())
