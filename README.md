# Sahayak — AI Payment Support & Resolution Platform

Paytm-style UPI app + SaaS support desk + AI agent (Gemini on Vertex,
Cognee memory, deterministic SLA/fraud engines). Built for the Paytm
Build for India finale (Team Maverick).

## Layout
- `sandbox/` — the UPI payments sandbox: 5-table log schema, calibrated
  synthetic seeder (~1.2M transactions), triage router, migrations.
- `backend/` — FastAPI app: live payment engine (payments write real causal
  rows across all rails), wallet ledger + multi-user auth, deterministic
  services (7-stage payment pipeline, SLA engine, fraud rules engine),
  AI orchestration (Gemini function-calling + deterministic fallback),
  Cognee memory layer, SaaS + conversation APIs.
- `ui/` — the Paytm-clone phone app (vanilla ES modules) AND the internal
  SaaS dashboard at `/dashboard` (pipeline, SLA, fraud, Sahayak chat).

## Run
```bash
python3 sandbox/seed.py            # build sandbox/sahayak.db (~1.2M txns, ~4 min)
python3 sandbox/migrate.py         # add auth/wallet columns if reusing an old DB
python3 backend/profiles.py        # seed the 4 demo profiles (A/B/C/D)
cd backend && ./run.sh             # http://localhost:8000 (+ /dashboard)
```
Demo login: mobile `9848012345`, PIN `2345` (any user's PIN = last 4 of mobile).
The ⚡ tab inside the app forces failure scenarios for demoing.

## Notes
- The 781 MB sandbox DB is generated, not committed — run the seeder.
- No API keys in code: Vertex Gemini uses gcloud ADC; Sarvam key (when the
  voice phase lands) goes in `backend/.env`.
