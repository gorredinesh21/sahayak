#!/usr/bin/env python3
"""
Sahayak end-to-end acceptance runner — 4 scenarios × 10 consecutive passes,
against the DEPLOYED application (or local via BASE).

Each pass = the complete user journey via the real APIs:
pay → backend outcome → persisted state → analysis/SLA/complaint → visualizer
events → AI conversation. Every assertion is recorded; a scenario's streak
resets to 0 on any failure. Output: tests/report.json + console table.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.environ.get("BASE", "http://127.0.0.1:8000").rstrip("/")
RUNS = int(os.environ.get("RUNS", "10"))
MOBILE, PIN = os.environ.get("DEMO_MOBILE", "9848012345"), "2345"

TOKEN = ""
results = []


def call(path, body=None, method=None, timeout=240):
    global TOKEN
    req = urllib.request.Request(
        f"{BASE}{path}", method=method or ("POST" if body is not None else "GET"),
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "x-sahayak-token": TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def check(pass_log, name, cond, evidence=""):
    pass_log["checks"].append({"check": name, "ok": bool(cond), "evidence": str(evidence)[:200]})
    if not cond:
        raise AssertionError(f"{name}: {str(evidence)[:160]}")


def wait_final(txn_id):
    for _ in range(40):
        v = call(f"/api/txn/{txn_id}")
        if not v.get("processing"):
            return v
        time.sleep(0.5)
    return call(f"/api/txn/{txn_id}")


def ai_says(txn_id, text):
    o = call("/api/saas/agent/open", {"txn_id": txn_id})
    r = call("/api/saas/agent/message", {"case_id": o["case_id"], "text": text})
    return o, r


def pay(vpa, amount_paise, scenario):
    t = call("/api/pay", {"vpa": vpa, "amount_paise": amount_paise,
                          "pin": "1234", "scenario": scenario})
    return wait_final(t["txn_id"])


# ------------------------------------------------------------ scenarios
def s1_wrong_recipient(run):
    log = {"scenario": "S1_wrong_recipient", "run": run, "checks": []}
    c = call("/api/contacts?limit=30")["items"]
    target = next((x for x in c if x["times_paid"] >= 1), c[0])
    v = pay(target["vpa"], 150000, "wrong_recipient")
    check(log, "payment succeeded (it does, that's the problem)",
          v["status"] == "SUCCESS", v["status"])
    check(log, "money went to a DIFFERENT (lookalike) recipient",
          v["to_vpa"] != target["vpa"], f"{target['vpa']} → {v['to_vpa']}")
    a = call("/api/scenario/analyze", {"txn_id": v["txn_id"],
                                       "intended_vpa": target["vpa"]})
    check(log, "analysis verdict flags wrong/possible",
          a["verdict"] in ("LIKELY_WRONG_RECIPIENT", "POSSIBLY_WRONG"), a["verdict"])
    check(log, "lookalike evidence present",
          any("lookalike" in e["label"].lower() for e in a["evidence"]),
          [e["label"] for e in a["evidence"]])
    check(log, "no fraud accusation (guardrail)",
          "fraud" not in json.dumps(a).lower().replace("fraud_reports", ""),
          "guardrails only")
    o, r = ai_says(v["txn_id"], "I think I paid the wrong person, please help")
    check(log, "AI replies substantively", len(r["reply"]) > 80, r["engine"])
    check(log, "AI does not promise auto-reversal",
          "auto-rever" not in r["reply"].lower().replace("auto-reversal of the failed", "x")
          or "dispute" in r["reply"].lower(), r["reply"][:100])
    return log


def s2_stuck_sla(run):
    log = {"scenario": "S2_stuck_sla_complaint", "run": run, "checks": []}
    v = pay("kirana@oksbi", 60000, "mode_b_yesterday")
    check(log, "backend produced PENDING (stuck)", v["status"] == "PENDING", v["status"])
    sla = call(f"/api/scenario/state_agreement/{v['txn_id']}")  # warm
    p = call(f"/api/saas/payment/{v['txn_id']}")
    check(log, "SLA engine reports EXPIRED",
          p["sla"].get("status") == "EXPIRED", p["sla"].get("status"))
    c = call("/api/complaints", {"txn_id": v["txn_id"],
            "category": "debited_not_credited",
            "description": "Debited but beneficiary not credited; pending > 24h"})
    check(log, "dispute filed (simulated) with ticket",
          c.get("ticket_ref", "").startswith("NPCI-"), c.get("ticket_ref"))
    check(log, "payload carries RRN + both banks",
          c["payload"]["rrn"] and c["payload"]["payerBank"] and c["payload"]["payeeBank"],
          c["payload"]["rrn"])
    st = call(f"/api/complaints/{c['complaint_id']}")
    check(log, "complaint status tracked", st["status"] in
          ("ACCEPTED", "UNDER_REVIEW", "RESOLVED"), st["status"])
    ev = call(f"/api/diag/{v['txn_id']}")["events"]
    check(log, "visualizer captured the complaint event",
          any(e["kind"] == "complaint" for e in ev), len(ev))
    o, r = ai_says(v["txn_id"], "mera paisa atak gaya, SLA cross ho gaya")
    check(log, "AI explains SLA breach / action",
          any(w in r["reply"].lower() for w in ("sla", "dispute", "escalat",
                                                "complaint", "समय")) ,
          r["reply"][:110])
    return log


def s3_no_debit(run):
    log = {"scenario": "S3_no_debit_retry", "run": run, "checks": []}
    v = pay("kirana@oksbi", 45000, "no_debit")
    check(log, "backend produced clean FAILURE", v["status"] == "FAILURE", v["status"])
    check(log, "no debit recorded", not v.get("debit_ts"), v.get("debit_ts"))
    rs = call(f"/api/scenario/retry_safety/{v['txn_id']}")
    check(log, "retry safety says SAFE", rs["safe_to_retry"] is True, rs["reason"])
    o, r = ai_says(v["txn_id"], "payment failed, I still need to pay, what do I do?")
    check(log, "AI does not block the retry",
          "duplicate" not in r["reply"].lower() or "safe" in r["reply"].lower(),
          r["reply"][:100])
    v2 = pay("kirana@oksbi", 45000, "success")
    check(log, "retry payment SUCCEEDS via backend", v2["status"] == "SUCCESS",
          v2["status"])
    return log


def s4_uncertain(run):
    log = {"scenario": "S4_state_disagreement", "run": run, "checks": []}
    v = pay("store.paytm@ybl", 90000, "uncertain")
    check(log, "payer view PENDING", v["status"] == "PENDING", v["status"])
    ag = call(f"/api/scenario/state_agreement/{v['txn_id']}")
    check(log, "receiver view CREDITED", ag["receiver_view"] == "CREDITED",
          ag["receiver_view"])
    check(log, "engine flags DISAGREEMENT", ag["agreement"] == "DISAGREEMENT",
          ag["agreement"])
    ev = call(f"/api/diag/{v['txn_id']}")["events"]
    check(log, "visualizer shows receiver-credit + backend-warning events",
          any(e["kind"] == "receiver_bank" for e in ev) and
          any(e["status"] == "warn" for e in ev), [e["kind"] for e in ev])
    rs = call(f"/api/scenario/retry_safety/{v['txn_id']}")
    check(log, "retry correctly BLOCKED (unknown debit state)",
          rs["safe_to_retry"] is False, rs["recommendation"])
    o, r = ai_says(v["txn_id"], "shop ko paisa mila but mera app me pending dikha raha hai")
    check(log, "AI addresses the mismatch",
          any(w in r["reply"].lower() for w in ("pending", "cred", "bank",
                                                "receiver", "लेन"))
          or "लाभार्थी" in r["reply"], r["reply"][:110])
    return log


SCENARIOS = [("S1", s1_wrong_recipient), ("S2", s2_stuck_sla),
             ("S3", s3_no_debit), ("S4", s4_uncertain)]


def main():
    global TOKEN
    print(f"Sahayak E2E acceptance · {BASE} · {RUNS} consecutive passes/scenario")
    TOKEN = call("/api/auth/login", {"mobile": MOBILE, "pin": PIN})["token"]
    summary = {}
    for code, fn in SCENARIOS:
        streak, log_file = 0, []
        for run in range(1, RUNS + 1):
            try:
                log = fn(run)
                log["pass"] = True
                streak += 1
                print(f"  ✅ {code} run {run}/{RUNS} pass (streak {streak})")
            except Exception as e:
                log = {"scenario": code, "run": run, "pass": False,
                       "error": str(e)[:300], "checks": locals().get("log", {}).get("checks", [])}
                streak = 0
                print(f"  ❌ {code} run {run} FAIL: {str(e)[:120]} (streak reset)")
            log_file.append(log)
        results.extend(log_file)
        summary[code] = {"consecutive_passes": streak, "accepted": streak >= RUNS}
    rep = {"base": BASE, "runs_required": RUNS, "summary": summary,
           "results": results, "generated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(os.path.dirname(__file__) or ".", exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__), "report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    print("\n=== ACCEPTANCE ===")
    for code, s in summary.items():
        print(f"{code}: {s['consecutive_passes']}/{RUNS} consecutive — "
              f"{'ACCEPTED ✅' if s['accepted'] else 'NOT ACCEPTED ❌'}")
    ok = all(s["accepted"] for s in summary.values())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
