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
from datetime import datetime

from google import genai
from google.genai import types

MAX_TURNS = 6

SYSTEM = """You are Sahayak, an AI payments-support agent inside a Paytm-like system.
You are handling ONE support case whose payment context is provided.

RULES (non-negotiable):
1. All facts (status, stage, amount, SLA numbers, fraud signals) come from the
   TOOL RESULTS provided to you. NEVER invent an SLA, a stage, a code or a score.
   If a fact is missing, call the tool that provides it.
2. If SLA status is ACTIVE: reassure with the exact remaining time and expiry.
   Do NOT escalate. If EXPIRED: say the deadline has passed and state the action taken.
3. If fraud category is HIGH/CRITICAL: do not promise reversal; say the case needs
   human risk-desk verification, list the concrete signals, and guide next steps.
4. Money is never moved by you. Complaints/escalations are records, not transfers.
5. Reply in the customer's language (English unless the customer writes Hindi/Hinglish).
6. Be concise (max ~120 words), warm, specific. Quote RRN and exact times when relevant.
7. End with ONE clear next step for the customer."""


# --------------------------------------------------------------------- tools
class ToolBelt:
    """Deterministic backend tools Gemini may call. Each returns plain JSON."""
    def __init__(self, services, db, memory):
        self.S = services
        self.db = db
        self.mem = memory

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
    def __init__(self, services, db, memory):
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
        ctx = (f"SUPPORT CASE CONTEXT (grounded, from the backend database):\n"
               f"payment: {json.dumps(self.tools.get_payment(txn_id))}\n"
               f"pipeline: failed_at={st['failed_at']}, status={st['payment_status']}\n"
               f"sla: {json.dumps({k: sla.get(k) for k in ('applicable','class','status','sla_duration','remaining_human','sla_expiry')})}\n"
               f"fraud: category={fr['category']} score={fr['score']} "
               f"signals={[s['rule'] for s in fr['signals']]}\n"
               f"detected_intent: {intent}\n")
        convo = [types.Content(role="user", parts=[types.Part(text=ctx)])]
        for m in history[-6:]:
            convo.append(types.Content(role=m["role"], parts=[types.Part(text=m["text"])]))
        convo.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

        steps = []
        for _ in range(MAX_TURNS):
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
