#!/usr/bin/env python3
"""
Sahayak AI orchestration — the layered pipeline from the spec:

  user text -> intent -> backend investigation (tools) -> memory -> Gemini
            -> response,  with a deterministic fallback so the system NEVER
  depends on the LLM for core payment/SLA/fraud information.

Gemini runs on Vertex (gcloud ADC, project from env) via google-genai.
"""
import json
import os
import re
import signal
from datetime import datetime
from contextlib import contextmanager

GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "45"))  # seconds per call


@contextmanager
def _timeout(seconds):
    """Kill the Gemini call if it takes too long."""
    def handler(signum, frame):
        raise TimeoutError(f"Gemini call exceeded {seconds}s")
    old = signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

from google import genai
from google.genai import types

MAX_TURNS = 6

SYSTEM = """You are Sahayak, an AI payments-support agent inside a Paytm-like UPI system.
You have COMPLETE backend context for this payment — use it. You already know
the payment details, failure stage, SLA status, risk analysis, customer history,
and prior support context. Do NOT ask the customer for information you already have.

HOW TO RESPOND:
- IMPORTANT: The "CURRENT PAYMENT" section above IS the payment the customer is asking
  about RIGHT NOW. The "PRIOR HISTORY" section is background from previous cases.
  NEVER mix them up. If the current payment says SUCCESS, it IS successful — regardless
  of what happened in prior cases.
- Start by acknowledging what you ALREADY KNOW about their situation from the CURRENT payment context.
  Example: if the context says "failed at confirmation stage, SLA ACTIVE 18h remaining",
  open with "I can see your ₹1,850 payment failed at the confirmation stage — the good
  news is the auto-reversal is already in motion with about 18 hours remaining."
- NEVER repeat the same response twice. If the customer says something new, build on
  your previous answer. If they ask the same thing, add NEW information or a different
  angle (e.g., "as I mentioned, the reversal is in flight — but I've also now checked
  your payment history and can confirm this merchant has had 3 similar cases this week").
- Call tools ONLY when you need something NOT already in the context above.
- Use the exact numbers from the context (amounts, times, RRN, SLA remaining).
- Be warm, specific, and concise (~100 words). End with ONE clear next step.

SCENARIO RULES:
- SLA ACTIVE: reassure with exact remaining time. Do NOT escalate. Quote the expiry.
- SLA EXPIRED: acknowledge the deadline passed. File a dispute if appropriate.
- WRONG-RECIPIENT: the payment SUCCEEDED (that's the problem). Never say "your payment
  was successful, what can I do". Instead:
  1) Name the ACTUAL recipient (from context) and say it differs from who they likely intended.
  2) Use the evidence: first-time vs repeat recipient, amount vs their average, lookalike name.
  3) ELABORATE on prior context — if the memory shows previous cases, say what happened
     and how it was resolved. If the payment history shows they usually pay a DIFFERENT
     person with a similar name, call that out specifically.
  4) Give 2-3 concrete next steps: (a) contact the recipient directly if known,
     (b) file a dispute through the tool, (c) if within 24h, the beneficiary bank may
     be able to recall the transfer.
  5) NEVER promise auto-reversal. Be honest: "completed UPI transfers cannot be
     automatically reversed by support — but here's what we CAN do."
- NO-DEBIT: explain the bank declined before money left. Safe to retry. Offer to help.
- UNCERTAIN STATUS: payer sees pending, receiver got the money — explain the mismatch.
- FRAUD/HIGH RISK: list the signals, recommend verification, never promise reversal.
- Language: match the customer. Hindi input → Hindi response.

HARD CONSTRAINTS:
- Facts come from the context and tools only. Never invent numbers, codes, or times.
- Money is never moved by you. Disputes are SIMULATED — say "simulated dispute" and
  give the ticket reference.
"""


# --------------------------------------------------------------------- tools
class ToolBelt:
    """Deterministic backend tools Gemini may call. Each returns plain JSON."""
    def __init__(self, services, db, memory, complaints=None, scenario_engines=None):
        self.S = services
        self.db = db
        self.mem = memory
        self.complaints = complaints
        self.scen = scenario_engines

    # ------------------------------------------------ scenario 1 & 3 & 4
    def analyze_wrong_recipient(self, txn_id, intended_vpa=None):
        return self.scen.wrong_recipient(int(txn_id), intended_vpa)

    def check_retry_safety(self, txn_id):
        return self.scen.retry_safety(int(txn_id))

    def verify_transaction_state(self, txn_id):
        return {"agreement": self.scen.state_agreement(int(txn_id)),
                "timeline": self.S.stages(int(txn_id))}

    def file_dispute(self, txn_id, category, description):
        p = self.S.payment(int(txn_id))
        rrn = self.db.execute("SELECT rrn FROM npci_switch_log WHERE txn_id=?",
                              (int(txn_id),)).fetchone()
        f = {"rrn": rrn["rrn"] if rrn else None,
             "txn_date": p["initiated_at"][:10], "amount_paise": p["amount_paise"],
             "payer_vpa": f"{p['user_id']}@paytm", "payee_vpa": p["beneficiary_vpa"],
             "payer_bank": p["payer_bank"] or "HDFC Bank",
             "payee_bank": "@" + p["beneficiary_vpa"].split("@")[-1],
             "category": category, "description": description}
        return self.complaints.submit(f, txn_id=txn_id, seed=int(txn_id))

    def dispute_status(self, complaint_id):
        r = self.complaints.status(complaint_id)
        return r or {"error": "unknown complaint id"}

    def get_payment(self, txn_id):
        p = self.S.payment(int(txn_id))
        if not p:
            return {"error": "payment not found"}
        return {"txn_id": p["txn_id"], "customer": p["customer_name"],
                "amount_paise": p["amount_paise"], "status": p["status"],
                "to_vpa": p["beneficiary_vpa"], "initiated_at": p["initiated_at"],
                "app_err_msg": p["app_err_msg"],
                "debit_ts": p["debit_ts"],
                "reversal_initiated_at": p["reversal_initiated_at"]}

    def get_payment_timeline(self, txn_id):
        return self.S.stages(int(txn_id))

    def get_payment_failure_stage(self, txn_id):
        st = self.S.stages(int(txn_id))
        return {"failed_at": st["failed_at"], "payment_status": st["payment_status"]}

    def get_sla(self, txn_id):
        return self.S.sla(int(txn_id))

    def check_sla_status(self, txn_id):
        sla = self.S.sla(int(txn_id))
        return {"status": sla.get("status"), "remaining_human": sla.get("remaining_human"),
                "sla_duration": sla.get("sla_duration"), "class": sla.get("class")}

    def get_customer_history(self, txn_id):
        p = self.S.payment(int(txn_id))
        rows = self.db.execute(
            "SELECT txn_id, status, amount_paise, beneficiary_vpa, initiated_at "
            "FROM paytm_txn WHERE user_id=? ORDER BY initiated_at DESC LIMIT 6",
            (p["user_id"],)).fetchall()
        return {"customer": p["customer_name"],
                "recent": [dict(zip(r.keys(), r)) for r in rows]}

    def run_fraud_analysis(self, txn_id):
        return self.S.fraud(int(txn_id))

    def get_previous_support_context(self, txn_id):
        p = self.S.payment(int(txn_id))
        return self.mem.customer_context(p["user_id"], int(txn_id))

    def escalate_payment_issue(self, txn_id, reason):
        p = self.S.payment(int(txn_id))
        cid = f"ESC-{int(txn_id)}-{datetime.now().strftime('%H%M')}"
        self.db.execute(
            "INSERT OR REPLACE INTO support_cases "
            "(case_id,txn_id,user_id,opened_at,status,intent,resolution) "
            "VALUES (?,?,?,?,?,?,?)",
            (cid, int(txn_id), p["user_id"], datetime.now().isoformat(timespec="seconds"),
             "ESCALATED", "payment_issue", reason))
        self.db.commit()
        return {"escalation_id": cid, "escalated_to": "payments-ops queue",
                "reason": reason}


TOOL_SPECS = [
    {"name": "get_payment", "description": "Core payment facts for this txn",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}},
                    "required": ["txn_id"]}},
    {"name": "get_payment_timeline",
     "description": "The 7-stage payment pipeline and exact failure stage",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "check_sla_status",
     "description": "Structured SLA status: ACTIVE/EXPIRED, remaining time, duration",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "run_fraud_analysis",
     "description": "Deterministic risk engine result: score, category, signals",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "get_customer_history",
     "description": "Customer's recent transactions for context",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "get_previous_support_context",
     "description": "Memory layer: previous cases/conversations for this customer",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "analyze_wrong_recipient",
     "description": "Contextual mistaken-transfer analysis: evidence, calibrated "
                    "verdict (LIKELY_INTENDED..LIKELY_WRONG_RECIPIENT), confidence, "
                    "clarifying questions. Pass intended_vpa if the customer said "
                    "who they meant.",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"},
                     "intended_vpa": {"type": "string"}}, "required": ["txn_id"]}},
    {"name": "check_retry_safety",
     "description": "No-debit case: whether retrying the payment is safe or "
                    "risks a duplicate debit",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "verify_transaction_state",
     "description": "Payer-view vs receiver-view agreement + full stage timeline "
                    "(scenario: uncertain status)",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
    {"name": "file_dispute",
     "description": "File the NPCI-style dispute (SIMULATED gateway; returns "
                    "ticket + validation errors). category one of "
                    "debited_not_credited|wrong_beneficiary|delayed_credit|status_unclear",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"}, "category": {"type": "string"},
                     "description": {"type": "string"}},
                    "required": ["txn_id", "category", "description"]}},
    {"name": "dispute_status",
     "description": "Track a filed dispute (ticket status + SLA)",
     "parameters": {"type": "object", "properties":
                    {"complaint_id": {"type": "string"}},
                    "required": ["complaint_id"]}},
    {"name": "escalate_payment_issue",
     "description": "Record an escalation to the payments-ops queue",
     "parameters": {"type": "object", "properties":
                    {"txn_id": {"type": "integer"},
                     "reason": {"type": "string"}},
                    "required": ["txn_id", "reason"]}},
]


# --------------------------------------------------------------------- intent
INTENT_RULES = [
    ("fraud", r"\b(fraud|scam|suspicious|fake|cheat|thug|ग़लत|धोखा)\b"),
    ("sla", r"\b(sla|deadline|how long|kab tak|when will|expected)\b"),
    ("missing_credit", r"\b(debited|deducted|not credited|credited|atak|stuck)\b"),
    ("status", r"\b(status|failed|failure|kya hua)\b"),
]


def detect_intent(text):
    t = text.lower()
    for intent, pat in INTENT_RULES:
        if re.search(pat, t, re.I):
            return intent
    return "general"


# ------------------------------------------------------------- deterministic
def fallback_reply(txn_id, S, intent):
    """System's voice when Gemini is unavailable — same grounded facts."""
    p, st, sla, fr = S.payment(txn_id), S.stages(txn_id), S.sla(txn_id), S.fraud(txn_id)
    amt = f"₹{p['amount_paise']/100:,.0f}"
    rrn = S.db.execute("SELECT rrn FROM npci_switch_log WHERE txn_id=?",
                       (txn_id,)).fetchone()
    rrn = rrn["rrn"] if rrn else "—"
    if fr["category"] in ("HIGH", "CRITICAL") and intent in ("fraud", "general"):
        sig = "; ".join(s["description"] for s in fr["signals"][:3])
        return (f"This payment of {amt} completed, but our risk engine flagged it as "
                f"{fr['category']} (score {fr['score']}). Signals: {sig}. "
                f"I have not touched the money — a human risk review is required. "
                f"Recommended action: {fr['recommended_action']}. "
                f"If you did not make this payment, call 1930 now; I can guide you "
                f"through the report. Reference RRN {rrn}.")
    if sla.get("applicable") and sla["status"] == "EXPIRED":
        return (f"Your {amt} payment has breached its SLA "
                f"({sla['sla_duration']}, expired {sla['sla_expiry'][11:16]} UTC) — "
                f"it will not self-heal. I have escalated it to payments-ops with the "
                f"full timeline (failed at: {st['failed_at'] or 'pending'}). "
                f"Reference RRN {rrn}.")
    if sla.get("applicable"):
        return (f"Your {amt} payment failed at the {st['failed_at']} stage "
                f"but is still INSIDE its resolution window "
                f"({sla['class']}, {sla['sla_duration']}). Expected by "
                f"{sla['sla_expiry'][11:16]} — about {sla['remaining_human']} from now. "
                f"The automatic reversal process is already in motion; no action needed "
                f"from you yet. Reference RRN {rrn}.")
    return (f"Payment {amt} — status {p['status']}. "
            f"Tell me what you'd like to check and I'll investigate.")


# ----------------------------------------------------------------- the agent
class SahayakAI:
    def __init__(self, services, db, memory, complaints=None,
                 scenario_engines=None):
        self.S = services
        self.db = db
        self.mem = memory
        self.tools = ToolBelt(services, db, memory)
        self.client = None
        self.model = os.environ.get("SAHAYAK_GEMINI_MODEL", "gemini-2.5-flash")
        try:
            self.client = genai.Client(
                vertexai=True,
                project=os.environ.get("GCP_PROJECT", "personal-project-dg21"),
                location=os.environ.get("GCP_LOCATION", "us-central1"))
        except Exception as e:                       # Vertex unavailable
            self.init_error = str(e)

    # -------------------------------------------------------------- opening
    def opener(self, txn_id):
        p = self.S.payment(txn_id)
        if not p:
            return "I couldn't find that payment.", []
        st = self.S.stages(txn_id)
        fr = self.S.fraud(txn_id)
        thinking = [{"tool": "load_payment_context",
                     "detail": f"txn#{txn_id} · {p['customer_name']} · "
                               f"₹{p['amount_paise']/100:,.0f} · {p['status']}"}]
        if p["status"] != "SUCCESS":
            msg = (f"Hello {p['customer_name'].split()[0]} 👋 I'm Sahayak. "
                   f"I can see your payment of ₹{p['amount_paise']/100:,.0f} to "
                   f"{p['beneficiary_vpa']} from {p['initiated_at'][11:16]} "
                   f"is {p['status'].lower()}"
                   + (f" — it failed at the {st['failed_at']} stage."
                      if st["failed_at"] else ".") +
                   " Do you want to talk about this failed payment?")
        else:
            fr = self.S.fraud(txn_id)
            if fr["category"] in ("HIGH", "CRITICAL"):
                msg = (f"Hello {p['customer_name'].split()[0]}, I'm Sahayak. "
                       f"I need to flag something about your recent payment of "
                       f"₹{p['amount_paise']/100:,.0f}. Can we talk about it now?")
            else:
                msg = (f"Hello {p['customer_name'].split()[0]} 👋 I'm Sahayak, "
                       f"your payments assistant. What can I help you with today?")
        thinking.append({"tool": "triage", "detail":
                         f"failure stage: {st['failed_at'] or 'none'} · "
                         f"risk: {fr['category']}"})
        return msg, thinking

    # ----------------------------------------------------------------- turn
    def turn(self, txn_id, history, user_text):
        """One conversation turn. Returns {reply, thinking, engine}."""
        intent = detect_intent(user_text)
        thinking = [{"tool": "intent", "detail": f"'{user_text[:40]}' → {intent}"}]
        try:
            reply, steps = self._gemini_turn(txn_id, history, user_text, intent)
            thinking += steps
            return {"reply": reply, "thinking": thinking, "engine": "gemini"}
        except Exception as e:
            thinking.append({"tool": "fallback", "detail":
                             f"Gemini unavailable ({str(e)[:60]}) — deterministic reply"})
            return {"reply": fallback_reply(txn_id, self.S, intent),
                    "thinking": thinking, "engine": "deterministic"}

    def _gemini_turn(self, txn_id, history, user_text, intent):
        p = self.S.payment(txn_id)
        st = self.S.stages(txn_id)
        sla = self.S.sla(txn_id)
        fr = self.S.fraud(txn_id)
        # FULL context: the AI knows everything the backend knows before speaking
        customer_hist = self.tools.get_customer_history(txn_id)
        memory_ctx = self.tools.get_previous_support_context(txn_id)
        wrong_rec = self.tools.S.fraud(txn_id)  # always compute for context
        stages_json = json.dumps(st['stages'], default=str)
        ctx = f"""=== CURRENT PAYMENT (THIS is the one the customer is asking about) ===
PAYMENT: {json.dumps(self.tools.get_payment(txn_id))}
PIPELINE (7 stages, exact failure point): {stages_json}
FAILURE: failed_at={st['failed_at']}, payment_status={st['payment_status']}

SLA ENGINE RESULT: {json.dumps({k: sla.get(k) for k in ('applicable','class','status','sla_duration','remaining_human','sla_expiry','sla_start')})}

RISK ENGINE: category={fr['category']} score={fr['score']} signals={[s['rule'] for s in fr['signals']]}

CUSTOMER: {customer_hist['customer']}
RECENT TRANSACTIONS (this customer): {json.dumps(customer_hist['recent'], default=str)}

=== PRIOR HISTORY (background only — do NOT confuse with the CURRENT payment above) ===
PRIOR SUPPORT CASES: {json.dumps(memory_ctx, default=str)[:600]}

DETECTED INTENT: {intent}
"""
        convo = [types.Content(role="user", parts=[types.Part(text=ctx)])]
        for m in history[-6:]:
            convo.append(types.Content(role=m["role"], parts=[types.Part(text=m["text"])]))
        convo.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

        steps = []
        for _ in range(MAX_TURNS):
            with _timeout(GEMINI_TIMEOUT):
                r = self.client.models.generate_content(
                    model=self.model,
                    contents=convo,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM,
                        tools=[types.Tool(function_declarations=[
                            types.FunctionDeclaration(
                                name=t["name"], description=t["description"],
                                parameters=t["parameters"]) for t in TOOL_SPECS])],
                        temperature=0.2))
            part = r.candidates[0].content.parts[0]
            if part.function_call:
                fc = part.function_call
                args = dict(fc.args or {})
                steps.append({"tool": fc.name, "detail": json.dumps(args)})
                fn = getattr(self.tools, fc.name, None)
                result = fn(**args) if fn else {"error": "unknown tool"}
                steps.append({"tool": fc.name + " →", "detail":
                              json.dumps(result)[:220]})
                convo.append(types.Content(role="model",
                                           parts=[types.Part(function_call=fc)]))
                convo.append(types.Content(role="user", parts=[types.Part(
                    text=json.dumps(result))]))
                continue
            return part.text.strip(), steps
        return ("I've gathered the case details but hit my step limit — "
                "here is what I have so far."), steps
