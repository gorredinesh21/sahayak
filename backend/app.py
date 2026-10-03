#!/usr/bin/env python3
"""
Sahayak v2 backend — FastAPI. Serves the Paytm-clone UI and the live APIs.

Run:  cd backend && uvicorn app:app --host 0.0.0.0 --port 8000
      (SAHAYAK_USER=dinesh.demo is the demo customer)
"""
import io
import json
import os
import secrets
import sys
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import qrcode
import qrcode.image.svg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sandbox"))
sys.path.insert(0, os.path.dirname(__file__))
from router import Router                                   # noqa: E402
from pay import PayEngine, MERCHANT_DISPLAY                 # noqa: E402
from services import Services                               # noqa: E402
from ai import SahayakAI                                    # noqa: E402
from memory import MemoryLayer                              # noqa: E402

DB_PATH = os.environ.get(
    "SAHAYAK_DB", os.path.join(os.path.dirname(__file__), "..", "sandbox", "sahayak.db"))
DEMO_USER = os.environ.get("SAHAYAK_USER", "dinesh.demo")
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")

engine = PayEngine(DB_PATH)
router = Router(DB_PATH)
SVC = Services(DB_PATH)
MEM = MemoryLayer(engine.db)
AI = SahayakAI(SVC, engine.db, MEM)
app = FastAPI(title="Paytm Demo — Sahayak")

SESSIONS = {}          # token -> user_id (in-memory; demo-scale auth)


def get_user(request: Request) -> str:
    token = request.headers.get("x-sahayak-token", "") or \
        request.cookies.get("sahayak_token", "")
    user = SESSIONS.get(token)
    if not user:
        raise HTTPException(401, "Please log in")
    return user


# ------------------------------------------------------------------- models
class LoginReq(BaseModel):
    mobile: str
    pin: str


class PayReq(BaseModel):
    vpa: str
    amount_paise: int
    pin: str
    scenario: str = "auto"        # auto|success|mode_a|mode_b_yesterday|u30


class AgentOpenReq(BaseModel):
    txn_id: int


# ------------------------------------------------------------------- basics
@app.get("/api/health")
def health():
    return {"ok": True, "db": DB_PATH, "user": DEMO_USER}


@app.post("/api/auth/login")
def login(req: LoginReq):
    mobile = "".join(c for c in req.mobile if c.isdigit())[-10:]
    row = engine.db.execute(
        "SELECT user_id, name, login_pin FROM users WHERE mobile=?", (mobile,)).fetchone()
    if not row or row["login_pin"] != req.pin:
        raise HTTPException(401, "Incorrect mobile number or PIN")
    token = secrets.token_hex(16)
    SESSIONS[token] = row["user_id"]
    resp = JSONResponse({"token": token, "user_id": row["user_id"],
                         "name": row["name"]})
    resp.set_cookie("sahayak_token", token, max_age=86400, samesite="lax")
    return resp


@app.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sahayak_token")
    return resp


@app.get("/api/auth/profiles")
def profiles():
    """Quick-login suggestions shown on the login screen."""
    rows = engine.db.execute(
        "SELECT user_id, name, mobile, login_pin FROM users "
        "WHERE user_id='dinesh.demo' OR (kyc_tier='FULL' AND user_id NOT LIKE '%demo%') "
        "ORDER BY CASE WHEN user_id='dinesh.demo' THEN 0 ELSE 1 END, ROWID LIMIT 4").fetchall()
    return {"items": [dict(zip(r.keys(), r)) for r in rows]}


@app.get("/api/me")
def me(request: Request):
    user_id = get_user(request)
    row = engine.db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "user missing — run the seeder")
    u = dict(zip(row.keys(), row))
    return {
        "user_id": u["user_id"],
        "mobile": u.get("mobile"),
        "name": u["name"],
        "initials": "".join(w[0] for w in u["name"].split()[:2]).upper(),
        "kyc_tier": u["kyc_tier"],
        "preferred_lang": u["preferred_lang"],
        "vpa": f"{u['user_id']}@paytm",
        "bank_display": "Paytm Payments Bank ••4291",
        "balance_paise": engine.balance_paise(user_id),
        "qr_payload": f"upi://pay?pa={u['user_id']}@paytm&pn={u['name']}&cu=INR",
    }


@app.get("/api/txn/list")
def txn_list(request: Request, limit: int = 40):
    return {"items": engine.history(get_user(request), limit)}


@app.get("/api/txn/{txn_id}")
def txn_detail(txn_id: int):
    v = engine.txn_view(txn_id)
    if not v:
        raise HTTPException(404, "no such txn")
    return v


@app.get("/api/beneficiary/resolve")
def beneficiary_resolve(vpa: str):
    r = engine.resolve(vpa)
    if not r:
        raise HTTPException(404, "Unknown UPI ID — check and try again")
    return r


# ------------------------------------------------------------------- paying
@app.post("/api/pay")
def pay(request: Request, req: PayReq):
    user_id = get_user(request)
    if req.amount_paise < 100:
        raise HTTPException(400, "amount must be at least ₹1")
    if not (4 <= len(req.pin) <= 6 and req.pin.isdigit()):
        raise HTTPException(400, "invalid PIN")
    txn_id = engine.pay(user_id, req.vpa, req.amount_paise, req.pin, req.scenario)
    return {"txn_id": txn_id}


# ------------------------------------------------------------------- QR
@app.get("/api/qr.svg")
def qr_svg(payload: str):
    img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage,
                      box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# ------------------------------------------------------------------- agent
# The triage verdict is REAL (router over the log tables). The thinking steps
# and messages are scripted previews per mode until the Gemini agent loop
# lands — the UI marks them with a small "scripted" badge in the dev drawer.
AGENT_SCRIPTS = {
    "A": {
        "opening_en": ("Your ₹{amount} payment to {to_name} failed on the recipient bank's side "
                       "({code}). Your money was debited — the automatic reversal is already "
                       "on its way back to your bank. Expected by {eta}. "
                       "Reference (RRN): {rrn}."),
        "opening_hi": ("नमस्ते {name} जी 🙏 आपका ₹{amount} का भुगतान {to_name} के बैंक की तकनीकी समस्या से "
                       "असफल हुआ है — पैसा आपके खाते से कट चुका है और ऑटो-रिवर्सल पहले ही शुरू हो चुका है। "
                       "अनुमानित वापसी: {eta} तक। रसीद नंबर (RRN): {rrn}"),
        "thinking": [
            {"tool": "check_bank_status", "detail": "debit ₹{amount} confirmed at {debit_ts}"},
            {"tool": "check_npci", "detail": "credit leg FAILED — {code} at beneficiary bank"},
            {"tool": "check_reversal", "detail": "auto-reversal initiated, in flight"},
            {"tool": "cognee.recall", "detail": "3 similar {code} cases at this bank — median 26h"},
            {"tool": "set_sla_timer", "detail": "T+1 stall-catch armed"},
        ],
    },
    "B": {
        "opening_en": ("Your ₹{amount} payment to {to_name} has been pending for {pending_h} hours — "
                       "past the 30-minute SLA, and the system has already tried auto-expiry once. "
                       "It will not fix itself now, so I have filed complaint {complaint} with your "
                       "RRN {rrn} and armed follow-up chases. Next update by 9:00 AM tomorrow."),
        "opening_hi": ("नमस्ते {name} जी 🙏 आपका ₹{amount} का भुगतान {pending_h} घंटे से लंबित है — "
                       "अब यह अपने आप ठीक नहीं होगा। मैंने आपकी ओर से कंप्लेंट {complaint} दर्ज कर दी है "
                       "(RRN: {rrn}) और बैंक से पीछा करने का टाइमर लगा दिया है। अगला अपडेट कल सुबह 9 बजे।"),
        "thinking": [
            {"tool": "check_bank_status", "detail": "debit ₹{amount} confirmed, no credit ack"},
            {"tool": "check_npci", "detail": "PENDING — auto-expiry already attempted, gave up"},
            {"tool": "cognee.recall", "detail": "similar T1 cases: filed complaints resolved in ~24h"},
            {"tool": "file_complaint", "detail": "complaint {complaint} filed with RRN {rrn}"},
            {"tool": "set_sla_timer", "detail": "T+1 / T+3 chase ladder armed"},
        ],
    },
    "C": {
        "opening_en": ("I need to flag something serious. Your ₹{amount} payment to {to_name} "
                       "completed successfully — but this UPI ID is new for you, the amount is "
                       "{ratio}× your usual, and this beneficiary has {reports} fraud reports. "
                       "I will NOT touch the money myself — I have packaged the complete case file "
                       "for our risk desk and I can walk you through freezing steps right now. "
                       "Shall I start?"),
        "opening_hi": ("{name} जी, एक गंभीर बात। आपका ₹{amount} इस UPI ID पर सफलतापूर्वक चला गया है — "
                       "लेकिन यह ID आपके लिए नई है, रकम आपकी आदत से {ratio} गुना है, और इस पर {reports} "
                       "fraud रिपोर्ट हैं। मैं खुद कोई पैसा नहीं हिलाऊंगा — पूरा केस-फाइल रिस्क डेस्क को भेज दी "
                       "है। क्या मैं आपको फ्रीज़ कराने के कदम बताऊं?"),
        "thinking": [
            {"tool": "cognee.recall", "detail": "beneficiary has {reports} fraud reports; linked to 2 prior cases"},
            {"tool": "check_stats", "detail": "first-time beneficiary; amount {ratio}× 30-day average"},
            {"tool": "HOLD — no auto-action", "detail": "hard rail: successful payment, fraud overlap → escalate only"},
            {"tool": "build_dossier", "detail": "timeline + RRN + reputation packaged"},
            {"tool": "escalate", "detail": "risk desk alerted with complete case file"},
        ],
    },
    # non-protocol leaves get honest previews too
    "WATCH": {
        "opening_en": ("Your ₹{amount} payment to {to_name} is pending inside the 30-minute SLA — "
                       "money is safe and the system will auto-reverse if it fails. "
                       "I have set a timer: if it is still pending at the deadline, I will act automatically."),
        "opening_hi": ("आपका ₹{amount} का भुगतान प्रोसेसिंग में है — SLA के अंदर। पैसा सुरक्षित है। "
                       "मैंने टाइमर लगा दिया है — डेडलाइन पर भी लंबित रहा तो मैं खुद कार्रवाई करूँगा।"),
        "thinking": [
            {"tool": "check_bank_status", "detail": "no credit ack yet, inside SLA window"},
            {"tool": "set_sla_timer", "detail": "watching — auto-act at SLA breach"},
        ],
    },
    "A_DONE": {
        "opening_en": ("Good news — the ₹{amount} that was stuck has already been reversed and "
                       "credited back at {reversal_credited_at}. Receipt: RRN {rrn}. "
                       "Anything else I can help with?"),
        "opening_hi": ("अच्छी खबर — आपका ₹{amount} वापस आ चुका है ({reversal_credited_at} पर)। "
                       "रसीद (RRN): {rrn}। कुछ और मदद चाहिए?"),
        "thinking": [
            {"tool": "check_reversal", "detail": "reversal credited at {reversal_credited_at}"},
        ],
    },
    "EXPLAIN": {
        "opening_en": ("This payment never left your account — it was declined before the debit "
                       "({code_msg}). Nothing is stuck. Would you like the likely fix?"),
        "opening_hi": ("यह भुगतान आपके खाते से निकला ही नहीं — डेबिट से पहले ही अस्वीकृत हो गया "
                       "({code_msg})। कुछ अटका नहीं है। समाधान बताऊं?"),
        "thinking": [
            {"tool": "check_bank_status", "detail": "no debit — nothing stuck"},
        ],
    },
}


@app.post("/api/agent/open")
def agent_open(req: AgentOpenReq):
    """The AI button. Triage is REAL (router over the logs); the message and
    thinking timeline are scripted previews per mode until the Gemini loop
    lands (marked scripted=true for the UI)."""
    verdict = router.triage(req.txn_id)
    v = engine.txn_view(req.txn_id)
    me_row = engine.db.execute(
        "SELECT u.name FROM users u JOIN paytm_txn t ON t.user_id=u.user_id WHERE t.txn_id=?",
        (req.txn_id,)).fetchone()
    name = me_row["name"].split()[0] if me_row else "Customer"
    stats = router.stats_for(engine.db.execute("SELECT user_id FROM paytm_txn WHERE txn_id=?", (req.txn_id,)).fetchone()["user_id"], v["to_vpa"])
    script = AGENT_SCRIPTS.get(verdict["mode"], AGENT_SCRIPTS["EXPLAIN"])

    amount = f"{v['amount_paise']/100:,.0f}"
    pending_h = ""
    if v["status"] == "PENDING" and v["initiated_at"]:
        dt = datetime.fromisoformat(v["initiated_at"])
        pending_h = f"{(datetime.now()-dt).total_seconds()/3600:.0f}"
    fmt = {
        "name": name, "amount": amount, "to_name": v.get("to_name") or "the beneficiary",
        "rrn": v.get("rrn") or "—",
        "code": v.get("fail_code") or (verdict.get("reason", "")[:2] if verdict["mode"] in ("A", "B") else ""),
        "code_msg": v.get("app_err_msg") or "declined by bank",
        "eta": "tomorrow " + (datetime.now() + timedelta(hours=26)).strftime("%I:%M %p").lstrip("0"),
        "pending_h": pending_h or "31",
        "complaint": f"CMP-{338000 + req.txn_id}",
        "ratio": f"{max(1, round(v['amount_paise']/max(stats.get('avg_amount_30d_paise',1),1))):,}",
        "reports": str((router.rails_for(req.txn_id) or {"fraud_reports_count": 0})["fraud_reports_count"] or 0),
        "debit_ts": (v.get("debit_ts") or "")[11:19],
        "reversal_credited_at": (v.get("reversal_credited_at") or "")[:16].replace("T", " "),
    }
    render = lambda s: s.format(**fmt)                      # noqa: E731
    return {
        "mode": verdict["mode"],
        "reason": verdict["reason"],
        "is_protocol_mode": verdict["is_protocol_mode"],
        "scripted": True,   # flips false when the Gemini loop takes over
        "opening_en": render(script["opening_en"]),
        "opening_hi": render(script["opening_hi"]),
        "thinking": [{"tool": s["tool"], "detail": render(s["detail"])}
                     for s in script["thinking"]],
        "brief": {
            "txn_id": req.txn_id, "rrn": v.get("rrn"), "amount_paise": v["amount_paise"],
            "status": v["status"], "to_vpa": v["to_vpa"],
            "first_time_beneficiary": bool(stats.get("first_time_beneficiary")),
        },
    }


@app.get("/api/dev/demo_cases")
def dev_demo_cases():
    rows = engine.db.execute(
        "SELECT txn_id, status, amount_paise, beneficiary_vpa FROM paytm_txn "
        "WHERE is_demo_case=1 ORDER BY txn_id").fetchall()
    return {"items": [dict(zip(r.keys(), r)) for r in rows]}


# ------------------------------------------------------------------- SaaS
PROFILE_TAGS = {"A": "Gateway failure", "B": "Debited · SLA active",
                "C": "SLA expired", "D": "Suspicious payment"}


def _case_id_for(txn_id):
    row = engine.db.execute(
        "SELECT case_id FROM support_cases WHERE txn_id=? AND status!='CLOSED' "
        "ORDER BY opened_at DESC LIMIT 1", (txn_id,)).fetchone()
    return row["case_id"] if row else None


@app.get("/api/saas/profiles")
def saas_profiles():
    rows = engine.db.execute(
        "SELECT txn_id, user_id FROM paytm_txn WHERE is_demo_case=2 "
        "ORDER BY txn_id").fetchall()
    items = []
    for tag, r in zip("ABCD", rows):
        p = SVC.payment(r["txn_id"])
        st = SVC.stages(r["txn_id"])
        sla = SVC.sla(r["txn_id"])
        fr = SVC.fraud(r["txn_id"])
        items.append({
            "tag": tag, "scenario": PROFILE_TAGS[tag], "txn_id": r["txn_id"],
            "customer": p["customer_name"], "amount_paise": p["amount_paise"],
            "payment_status": p["status"], "failed_at": st["failed_at"],
            "sla_status": sla.get("status"), "risk_category": fr["category"],
            "risk_score": fr["score"]})
    return {"items": items}


class SaasOpenReq(BaseModel):
    txn_id: int


class SaasMsgReq(BaseModel):
    case_id: str
    text: str


@app.get("/api/saas/payment/{txn_id}")
def saas_payment(txn_id: int):
    p = SVC.payment(txn_id)
    if not p:
        raise HTTPException(404, "no such payment")
    st = SVC.stages(txn_id)
    sla = SVC.sla(txn_id)
    fr = SVC.fraud(txn_id)
    hist = engine.history(p["user_id"], limit=6)
    cases = [{"case_id": c["case_id"], "status": c["status"], "intent": c["intent"],
              "opened_at": c["opened_at"], "resolution": c["resolution"]}
             for c in engine.db.execute(
                 "SELECT * FROM support_cases WHERE txn_id=? ORDER BY opened_at DESC",
                 (txn_id,)).fetchall()]
    rrn = engine.db.execute("SELECT rrn FROM npci_switch_log WHERE txn_id=?",
                            (txn_id,)).fetchone()
    return {"payment": dict(zip(p.keys(), p)), "stages": st, "sla": sla,
            "fraud": fr, "history": hist, "support_cases": cases,
            "rrn": rrn["rrn"] if rrn else None}


@app.post("/api/saas/agent/open")
def saas_agent_open(req: SaasOpenReq):
    """Sahayak opens ALREADY knowing the failed payment (spec §7)."""
    p = SVC.payment(req.txn_id)
    if not p:
        raise HTTPException(404, "no such payment")
    case_id = _case_id_for(req.txn_id) or (
        f"CASE-{req.txn_id}-{datetime.now().strftime('%H%M%S')}")
    engine.db.execute(
        "INSERT OR IGNORE INTO support_cases "
        "(case_id,txn_id,user_id,opened_at,status) VALUES (?,?,?,?,?)",
        (case_id, req.txn_id, p["user_id"],
         datetime.now().isoformat(timespec="seconds"), "OPEN"))
    opener, thinking = AI.opener(req.txn_id)
    engine.db.execute(
        "INSERT INTO support_messages (case_id, role, text, thinking, created_at) "
        "VALUES (?,?,?,?,?)",
        (case_id, "assistant", opener, json.dumps(thinking),
         datetime.now().isoformat(timespec="seconds")))
    engine.db.commit()
    return {"case_id": case_id, "opener": opener, "thinking": thinking,
            "memory_mode": MEM.mode}


@app.post("/api/saas/agent/message")
def saas_agent_message(req: SaasMsgReq):
    prior = [{"role": m["role"], "text": m["text"]} for m in engine.db.execute(
        "SELECT role, text FROM support_messages WHERE case_id=? ORDER BY msg_id",
        (req.case_id,)).fetchall()]
    engine.db.execute(
        "INSERT INTO support_messages (case_id, role, text, created_at) "
        "VALUES (?,?,?,?)",
        (req.case_id, "user", req.text,
         datetime.now().isoformat(timespec="seconds")))
    engine.db.commit()
    case = engine.db.execute("SELECT * FROM support_cases WHERE case_id=?",
                             (req.case_id,)).fetchone()
    out = AI.turn(case["txn_id"], prior, req.text)
    engine.db.execute(
        "INSERT INTO support_messages (case_id, role, text, thinking, created_at) "
        "VALUES (?,?,?,?,?)",
        (req.case_id, "assistant", out["reply"], json.dumps(out["thinking"]),
         datetime.now().isoformat(timespec="seconds")))
    engine.db.commit()
    return out


@app.get("/api/saas/case/{case_id}")
def saas_case(case_id: str):
    msgs = engine.db.execute(
        "SELECT role, text, thinking, created_at FROM support_messages "
        "WHERE case_id=? ORDER BY msg_id", (case_id,)).fetchall()
    return {"messages": [dict(zip(m.keys(), m)) for m in msgs]}


@app.post("/api/saas/case/{case_id}/close")
def saas_case_close(case_id: str):
    MEM.remember_case(case_id)
    return {"case_id": case_id, "status": "CLOSED", "memory_mode": MEM.mode}


@app.get("/api/ai/status")
def ai_status():
    st = {"gemini": "vertex-ok" if AI.client else
          f"unavailable: {getattr(AI, 'init_error', 'n/a')}",
          "model": AI.model, "memory": MEM.mode,
          "fallback": "deterministic replies active if Gemini fails"}
    try:
        r = AI.client.models.generate_content(
            model=AI.model, contents="reply with the single word OK")
        st["gemini_probe"] = (r.candidates[0].content.parts[0].text or "").strip()[:20]
    except Exception as e:
        st["gemini_probe"] = f"failed: {str(e)[:80]}"
    return st


# ------------------------------------------------------------------- static UI
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with open(os.path.join(UI_DIR, "dashboard.html")) as f:
        return HTMLResponse(f.read())


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(UI_DIR, "index.html")) as f:
        return HTMLResponse(f.read())


app.mount("/src", StaticFiles(directory=UI_DIR + "/src"), name="src")
