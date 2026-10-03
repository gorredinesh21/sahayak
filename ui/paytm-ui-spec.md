# Sahayak — Paytm-Style UI Build Spec

**Project:** Sahayak — AI payment-dispute agent demo (Paytm Build for India finale)
**Document:** Frontend UI specification, build-ready (no further design decisions required)
**Date:** October 2026
**Target:** Single lightweight web app (vanilla HTML/CSS/JS recommended), runs locally on a 7.5 GB RAM laptop and in one container on Cloud Run.

> **Legal note:** This is a look-alike recreation for a hackathon demo. We do NOT copy Paytm logos, artwork, fonts, or screenshots. App name shown is **"Paytm Demo"** with our own logo placeholder (a simple rounded rectangle wordmark "paytm demo" in Paytm-like colors). Colors/layout/copy patterns are generic UI conventions; nothing copyrighted is embedded.

---

## 1. Design System

### 1.1 Color palette

Paytm's brand is a two-tone blue system (verified from multiple brand-color references; exact hexes vary ±1 between sources):

| Token | Hex | Usage |
|---|---|---|
| `--paytm-cyan` | `#00BAF2` | Signature cyan. Home header gradient start, links, primary accents, active states |
| `--paytm-cyan-deep` | `#0099D8` | Gradient end / pressed state of cyan |
| `--paytm-navy` | `#002E6E` | Dark navy (Prussian blue). Header gradient end, headings, footer strip, logo wordmark |
| `--paytm-navy-soft` | `#0B3D8C` | Secondary navy for icon strokes (approx) |
| `--bg` | `#F2F4F8` | App background (light blue-grey) |
| `--surface` | `#FFFFFF` | Cards, sheets |
| `--ink` | `#17212B` | Primary text |
| `--ink-2` | `#5A6B7B` | Secondary text (labels, captions) |
| `--ink-3` | `#93A1B0` | Tertiary text (timestamps, hints) |
| `--line` | `#E4EAF0` | Hairline dividers, card borders |
| `--success` | `#2FA84F` | Payment success green (approx — Paytm uses a mid-tone green close to `#34A853`/`#2FA84F`) |
| `--success-bg` | `#E9F9EF` | Success tint background |
| `--failure` | `#E23A3A` | Payment failure red (approx — close to Material red `#D93025`) |
| `--failure-bg` | `#FDECEC` | Failure tint background |
| `--pending` | `#F5A623` | Pending/processing amber (approx) |
| `--pending-bg` | `#FFF6E5` | Pending tint background |
| `--agent` | `#7B4DFF` | Sahayak AI accent (violet) — used ONLY on the AI button and agent chat, so the AI surfaces read as "new but native" |
| `--agent-bg` | `#F1EBFF` | Agent tint background |
| `--chat-bg` | `#EEF2F6` | Agent chat canvas |

Anything above marked (approx) is tuned by eye against Paytm screenshots; the two blues are exact brand colors.

### 1.2 The signature home header gradient

Paytm's home header is a diagonal cyan→navy blend. Use exactly:

```css
.home-header {
  background: linear-gradient(160deg, #00BAF2 0%, #0E8FDB 34%, #1B5FC9 62%, #002E6E 100%);
  border-radius: 0 0 24px 24px; /* bottom corners rounded (approx) */
  color: #FFFFFF;
}
```

Secondary headers (payment status screens) use the same gradient but with a flat tint variant when the status is FAILURE (use `--failure-bg` flat background with white card) — Paytm status screens are predominantly WHITE with a colored status icon, not full-bleed color.

### 1.3 Typography

Paytm's logo is a custom rounded lowercase sans; the app UI has historically used Roboto-family/system sans (approx). Closest free Google Font equivalents:

| Role | Font | Fallback stack |
|---|---|---|
| Logo / wordmark + big numerals | **Baloo 2** (weight 600–700) — rounded, lowercase-friendly, close to the Paytm wordmark feel | `"Baloo 2", "Nunito", system-ui, sans-serif` |
| Body / UI / labels | **Nunito Sans** (weights 400/600/700) — rounded-humanist, very close to Paytm's in-app text | `"Nunito Sans", "Segoe UI", Roboto, system-ui, sans-serif` |
| Monospace (RRN, UPI IDs, txn IDs) | **JetBrains Mono** or `ui-monospace` — used for reference numbers so they read as "machine data" | `"JetBrains Mono", ui-monospace, Menlo, monospace` |

Type scale (px, inside the 390px phone frame):

| Token | Size / line-height | Weight | Usage |
|---|---|---|---|
| `display-amount` | 56 / 1.1 | 700 (Baloo 2) | Big rupee amount on pay/status screens |
| `display-xl` | 28 / 1.2 | 700 | "Payment Failed" title |
| `title` | 20 / 1.3 | 700 | Screen titles, card headers |
| `body-lg` | 16 / 1.45 | 400–600 | Message bubbles, list primary text |
| `body` | 14 / 1.5 | 400–600 | Default UI text |
| `caption` | 12 / 1.4 | 400–600 | Labels, timestamps |
| `micro` | 10.5 / 1.3 | 600 | Chips, badges, ALL-CAPS eyebrow labels |

Load via Google Fonts CSS2 link (2 families + mono, subset `latin`): ~90 KB — acceptable. If offline demo is required, self-host the woff2 files in `/ui/src/assets/fonts/`.

### 1.4 Border radius scale

| Token | Value | Usage |
|---|---|---|
| `r-xs` | 6px | Chips, small badges |
| `r-sm` | 10px | Small buttons, inputs |
| `r-md` | 14px | Cards, list rows |
| `r-lg` | 20px | Sheets, modals, big buttons |
| `r-xl` | 24px | Home header bottom corners, agent button |
| `r-full` | 999px | Pills, avatars, quick-reply chips |

Paytm's look is **soft-rounded everywhere** — never sharp corners on cards or buttons.

### 1.5 Spacing scale

4px base grid: `4, 8, 12, 16, 20, 24, 32, 40, 48`. Screen horizontal padding: 16px. Card inner padding: 16px. List row height: 64px. Bottom nav height: 64px + 12px safe-area.

### 1.6 Elevation / shadows

```css
--shadow-card: 0 1px 2px rgba(16, 42, 82, .06), 0 4px 12px rgba(16, 42, 82, .06);
--shadow-fab:  0 6px 20px rgba(0, 186, 242, .35);
--shadow-agent: 0 8px 24px rgba(123, 77, 255, .35);
```

Paytm is a LOW-shadow app: mostly flat white cards with hairline `--line` borders; shadows only on floating elements (FAB, sticky CTA, toasts).

### 1.7 Buttons

| Style | Spec |
|---|---|
| **Primary (cyan)** | Fill `--paytm-cyan`, text white, 14px/700, `r-full` pill (Paytm CTAs are fully rounded pills), height 48px, full-width inside 16px padding. Pressed: `--paytm-cyan-deep` + `transform: scale(.98)`. Disabled: `#B8E4F7` fill, white text |
| **Secondary (outline)** | 1.5px `--paytm-cyan` border, cyan text, transparent fill, pill |
| **Paytm-native failure CTA** | Fill `--paytm-navy`, white text, pill, height 48px ("Get Help" style) |
| **Ask Sahayak AI (ours)** | Fill `linear-gradient(90deg,#7B4DFF,#5E8BFF)`, white text, pill, height 52px, leading icon = simple sparkle glyph drawn in inline SVG (4-point star), `--shadow-agent`. This is the ONLY violet element in the app |
| **Keypad key** | 80×56px, transparent, `--ink` digit 24px/500; press flash `rgba(0,186,242,.12)` rounded 12px, `scale(.96)` 80ms |

### 1.8 Iconography

Do not copy Paytm's icons. Use **inline SVG line icons, 1.8px stroke, rounded caps** (draw by hand or take from MIT-licensed Lucide/Feather — self-copy only the few needed paths, no icon-font dependency). Icon box: 24px default, 20px inline, 56px tiles in quick-action grid with a `#E8F7FD` tinted circle behind.

### 1.9 Haptics-like press states (critical for "feels real")

Every tappable element: `transition: transform .08s, filter .08s` and on `:active` → `scale(.96)` + brightness(.97). Add a global "tap" sound (see §6) and `navigator.vibrate(10)` where supported.

---

## 2. Screen-by-Screen Spec

App shell: screens are full-height panels inside the phone frame; navigation is a simple stack (`push`/`pop`) with 240ms slide-in from right (CSS transform, no library). Screen IDs below (`S1`…`S6`) are the route names.

### S1 — Home

**Layout (top → bottom):**

1. **Status bar area** (rendered by phone frame, §4 — not part of the screen).
2. **Header band on the cyan→navy gradient (~168px):**
   - Row 1 (h 48): logo placeholder "paytm demo" wordmark (Baloo 2, white, 20px, lowercase — our own drawn text, no copied logo) left; right: bell icon with red dot badge, avatar circle (36px, initials "AR").
   - Row 2 (h ~56): **Search bar** — white pill, `Search for mobile no., UPI ID, QR` in `--ink-3`, magnifier icon. Tapping it is a no-op that focuses S2 entry (nice-to-have).
   - Row 3 (h ~48): **Balance card row** — a translucent white card (`rgba(255,255,255,.16)`, `r-md`, blur 8px) showing "UPI Balance" caption (white 80%) + `₹ 12,430.50` (Baloo 2, 22px, white) + small "Total UPI Bank Balance" sub-caption. Right side: chevron into S6.
3. **Primary actions card** (white, `r-lg`, `-16px` overlap onto header, shadow-card):
   4 equal tiles 64px wide, each = 56px tinted-circle icon + 11px/600 label:
   - **Scan & Pay** (QR icon, cyan circle) → opens S2-scan
   - **To Mobile Number** (phone icon) → S2
   - **To UPI ID / App** (at-sign icon) → S2
   - **Balance & History** (book/ledger icon) → S6
4. **"Recharge & Pay Bills" section** — `micro` ALL-CAPS eyebrow label `--ink-3`, then a white card with a 4-column grid of small tiles (28px icon + 10.5px label): `Mobile Recharge`, `DTH`, `Electricity`, `Loan EMI`, `Rent`, `Credit Card`, `More`. Non-functional for the demo: tapping shows a toast "Not available in demo".
5. **Recent transactions preview** — header row "Recent Transactions" + "View All →" (cyan, links S6). 3 rows (same row component as S6). Tapping a row → S4.
6. **Bottom navigation** (fixed, white, top hairline): Home (active cyan), Balance & History, Scan (center FAB: 56px cyan circle, QR glyph, `--shadow-fab`), Cards, Profile. Non-primary tabs show toast "Not available in demo".

**States:** normal only. Data: demo fixtures (§3.4).

### S2 — Pay Flow (4 sub-steps, one screen with state machine)

Route `#/pay`. State machine: `entry → verified → amount → pin → processing → (S3)`.

**S2a Entry — "Pay by UPI ID / QR":**
- Header: white, back arrow, title "Pay by UPI ID" (or "Scan & Pay" when arriving from scan/QR FAB — the fake camera view: dark panel with a rounded-square viewfinder bracket in cyan, an animated scan line 2s loop, and after 1.5s "found" animation → auto-advances with the QR's payload).
- Body: input field (16px pad, 52px, `r-sm`, 1.5px `--line` border, focus border cyan) placeholder `name@bank`. Below: "Verify" primary button (disabled until ≥3 chars typed).
- Under input: caption `Example: 9876543210@paytm` and 2 demo quick-fill chips: `kirana.store@ybl`, `fraudster@upi`.

**S2b Verified:**
- After `POST /api/pay/verify` returns `{ name: "KIRANA STORE" }`:
- White centered card: avatar circle (navy, shop glyph), **`KIRANA STORE`** (18px/700, ALL CAPS — Paytm shows verified names in caps), below `kirana.store@ybl` (mono, `--ink-2`), below green tick-in-circle + `Verified` (12px, `--success`).
- Amount input auto-focused. **Amount entry (this screen doubles as S2c):**
  - Center: `₹` 24px `--ink-3` + big amount display (Baloo 2, `display-amount` 56px, `--ink`; starts `0` in `--ink-3`).
  - Below: caption `Paying to KIRANA STORE` (12px, `--ink-2`).
  - Optional "Add a note" pill (12px, `--ink-2`, dashed border).
- **Custom keypad** (fixed bottom, 4×3: 1–9, ⌫, 0, and a cyan "→" arrow in the bottom-right key):
  - Digits append; format live in Indian grouping (`§6.1`).
  - The arrow key = "Proceed", enabled when amount ≥ 1.
  - Haptic-style flash on each keypress; long-press ⌫ (400ms) clears.
- Proceed → S2d PIN.

**S2d UPI PIN entry:**
- Top: lock icon + caption `Enter UPI PIN to pay ₹115.00` (amount in 600 weight).
- **PIN dots:** 6 circles, 14px, gap 20px, centered at ~35% viewport height. Empty: 2px `--ink-3` border, transparent. Filled: solid `--ink` with a 120ms pop (`scale 1.25→1`) animation. (Paytm PINs are 4–6 digits; we use 6. NPCI redesigned the PIN screen in 2025 to show the payee verified name — include a small green-tick row `KIRANA STORE · Verified` above the dots, approx.)
- Same keypad (no arrow key; auto-submits on 6th digit; ⌫ deletes).
- Any 6 digits work; PIN is never displayed or logged.
- On 6th digit → S2e.

**S2e Processing:**
- Full-screen white. Centered: the Paytm-style loader — a cyan ring spinner (2px border, 40px) around a small white rupee ₹ glyph, plus caption `Processing your payment…` (14px `--ink-2`), sub-caption `Do not press back or close the app` (11px `--ink-3`).
- Duration is driven by backend (`POST /api/pay` returns the outcome); target 2.5–4s for suspense. Then route to S3-success / S3-failure / S3-pending per scenario.

### S3 — Payment Status Screens

All variants share a structure: full-height white screen; big status illustration zone (top 38%); amount; summary card; actions.

**S3-SUCCESS:**
- Illustration: 96px circle `--success-bg` containing an 88px green circle with a white SVG checkmark that draws itself (CSS `stroke-dashoffset` animation, 500ms, 150ms delay) + an outer expanding ring pulse (2 rings, `--success` at 30%/15% opacity, scale 1→1.6, fade out, 1.2s).
- Title `Payment Successful` (`display-xl`, `--ink`). Below: `₹115.00` (`display-amount`, `--ink`), below `To KIRANA STORE · kirana.store@ybl` (13px, `--ink-2`).
- Summary card (white, hairline, `r-md`, rows of label:value):
  - `UPI Ref No` → mono `410234567891`
  - `Date & Time` → `Today, 2:31 PM`
  - `Debited from` → `HDFC Bank ••4291`
- Actions: primary navy pill `Done` (→ S4 detail of this txn), secondary outline `Share receipt` (toast).
- Optional success "ding" sound (§6.3).

**S3-FAILURE (the money screen for our demo):**
- Same skeleton, inverted palette:
- Illustration: 96px `--failure-bg` circle with 72px `--failure` circle containing a white **×** cross (two 6px rounded bars) — no animation flourish; a single slow "drop-in + settle" (translateY -8px→0, 300ms) reads heavier than success.
- Eyebrow (micro, ALL-CAPS, `--failure`): `PAYMENT FAILED` (approx copy; Paytm uses this or "Transaction Failed").
- Title `display-xl` `--ink`: **`Money debited but not credited?`** — no. Exact copy Paytm shows on debited-but-failed cases (approx, per Paytm support guidance): title = **`Payment Failed`**, sub-line = **`Money debited but not received by the recipient. It will be auto-reversed within T+1 as per RBI guidelines.`** Keep the sub-line 13px `--ink-2`, max 2 lines.
- Amount `₹115.00` (`display-amount`) + `To KIRANA STORE · kirana.store@ybl`.
- Amber inline banner (12px, `--pending-bg` bg, `--pending` text, `r-xs`): `If money is not refunded within 3-5 business days, contact 24x7 Help.` (approx, mirrors Paytm support copy).
- Summary card: `UPI Ref No` (mono, red-tinted 600 weight), `Date & Time`, `Debited from`, `Failure reason` → `Bank declined: switching timeout (N66)` (scenario text).
- **Action stack (bottom, fixed, 16px pad):**
  1. **OUR BUTTON — "Ask Sahayak AI"** — placed FIRST, full-width, violet gradient pill, 52px, sparkle icon + label + micro sub-label under it inside the button: `Resolves in ~2 min` (10.5px, white 80%). This placement (top of the action stack, directly under the summary card) is how Paytm places its primary contextual help CTA, so ours reads native while the violet makes it pop on stage.
  2. Secondary navy pill `Contact 24x7 Help` (→ opens S5 pre-seeded WITHOUT the AI branding: label it "24x7 Help"; for the demo both paths open the same S5 agent, but this one shows a brief "Connecting to assistant…" 600ms interstitial so the AI button feels faster).
  3. Text link (13px cyan) `View transaction details` → S4.

**S3-PENDING:**
- Same skeleton with `--pending`: illustration = amber circle with a white clock glyph (slightly rotating second-hand, 8s linear loop). Eyebrow `PAYMENT PENDING`; title `Payment Pending` (approx; Paytm: "Your payment is pending confirmation"); sub-line `Usually confirmed within 30 minutes. Money is safe and will be auto-reversed if it fails.` Amber banner: `Bank is taking longer than usual (SLA: 30 min). Status will update automatically.`
- Same action stack as FAILURE (`Ask Sahayak AI` first).

### S4 — Transaction Detail

Route `#/txn/:id`. This must look like a receipt — dense, mono numbers, hairline rows.

**Layout:**
1. Header: white, back arrow, title `Transaction Details`, right overflow (⋮) icon → toast.
2. Status block (centered, 96px pad-top): small 56px status icon (same family as S3, smaller), eyebrow status chip (pill: `FAILED` red bg tint / `SUCCESS` green / `PENDING` amber), amount `display-amount`, payee line `KIRANA STORE` (16px/600) + `kirana.store@ybl` (12px mono `--ink-2`).
3. **"Details" card** — Paytm lists reference numbers under a details section on the txn screen (the RRN appears as **"UPI Ref No"**, a 12-digit number, in txn details and on the payment screenshot). Card = white, `r-md`, hairline, rows 48px each, label left (13px `--ink-2`), value right (13px `--ink`, mono where marked):

| Label | Value (example) | Style |
|---|---|---|
| `Status` | `Failed - money debited` | red 600 |
| `Amount` | `₹115.00` | |
| `UPI Transaction ID` | `519224310234` | mono |
| `UPI Ref No / RRN` | `410234567891` | mono + copy icon (taps → copy + toast `RRN copied`) |
| `Debited from` | `HDFC Bank ••4291` | |
| `To VPA` | `kirana.store@ybl` | mono |
| `From VPA` | `arjun.r@paytm` | mono |
| `Date & Time` | `1 Oct 2026, 2:31:04 PM` | |
| `Remark` | `(empty for demo)` | |
| `Gateway` | `UPI Switch · NPCI` | |

4. If status ≠ SUCCESS: a red-tinted strip above the actions: `Need help with this payment?` + small violet text button `Ask Sahayak AI` (opens S5 with this txn pre-loaded).
5. Actions: `Report an issue` (outline), `Share receipt` (outline), `Contact 24x7 Help` (text link).
6. Data source: `GET /api/txn/:id`.

### S5 — AI Agent Chat ("Sahayak — 24x7 Help")

Route `#/help/:txnId`. This is the wow screen; it must look like a native Paytm help-chat that happens to be AI.

**Layout:**
1. **Header** (56px, sticky, white, hairline bottom): back arrow; agent avatar = 36px violet-gradient circle with sparkle glyph; title `Sahayak Assistant` (15px/700) + subtitle `Paytm 24x7 Help · Online` (11px, green dot + `--success` text). Right: ⋮ menu → toast.
2. **Case banner** (below header, `--agent-bg`, 12px, `r-xs`, 12px margins): `Case #PT-88214 · ₹115.00 to KIRANA STORE · RRN 4102…` — shows the agent already has context (auto-loaded via `POST /api/agent/open {txnId}`).
3. **Chat canvas** (`--chat-bg`, scrollable, 16px pad, column of bubbles; newest at bottom; auto-scroll on new events):

   - **Agent bubble**: white, `r-md` with a top-left 4px radius (chat-notch), max-width 78%, 14px/1.5 body, tail-less; timestamp 10px `--ink-3` below-right. Enter animation: translateY 8px + fade, 180ms.
   - **User bubble**: cyan `#D6F3FD` tint (approx Paytm help bubble; a light cyan), same geometry, right-aligned.
   - **Quick-reply chips**: horizontally scrollable row of pills (white, 1px `--line`, 13px, `r-full`, 36px) attached under an agent bubble. Tapping sends as user message and disables the row.
   - **Agent first message (exact copy):**
     > Hi Arjun, I'm Sahayak. I can see your payment of ₹115.00 to KIRANA STORE failed while your bank debited the amount. I've already pulled up the transaction — want me to investigate right now?
     
     Chips: `Yes, investigate` · `When will I get money back?` · `Talk to a human`

4. **The "thinking view" — tool-call timeline (our signature element):**

   Rendered as **collapsed gray cards BETWEEN messages** — a native-looking pattern (like system messages in banking chats), NOT a side panel:

   ```
   [case banner]
   [user: Ask Sahayak AI]              ← implicit user action that opened chat
   [ TOOL TIMELINE CARD  ▾ ]           ← collapsed gray card (see below)
   [agent: Found the issue — read on]
   [chips…]
   ```

   - **Collapsed state** (default after events finish): full-width card, `#EFF3F7` bg, `r-sm`, 40px, layout: 16px spinner-or-check icon · label `Sahayak checked 4 sources` (12px/600 `--ink-2`) · right chevron `▾`. Tap → expands (240ms height transition).
   - **Expanded state**: same card grows into a vertical timeline (left 2px `#C6D2DE` rail, 12px nodes):
     - Each tool call = a row: status glyph (spinner cyan while running / `✓` green when done / `!` amber if warning) + title 13px/600 + optional detail line 11.5px mono `--ink-2`.
     - **Exact tool-call rows per scenario (Mode A):**
       1. `Fetching transaction details` · `GET txn 519224310234`
       2. `Checking NPCI switch status` · `RRN 410234567891 → response: DEBITED, credit NACK`
       3. `Verifying beneficiary bank (Yes Bank)` · `IFSC YESB0PTMUPI · credit attempt timed out`
       4. `Reading RBI T+1 auto-reversal rule` · `UPI Procedural Guidelines §10.2`
       5. `Filing dispute ticket` · `Ticket #PT-88214 raised`
     - While the agent is working, the card shows the live sequence: rows appear **one by one** (each new row: spinner for 0.8–1.6s → flips to ✓), and the collapsed label live-updates: `Sahayak is checking… (2/5)` with a subtle pulse. Auto-scroll keeps the active row visible.
   - **Streaming protocol:** SSE (see §5.5). Events: `tool_start {title, detail}`, `tool_end {ok}`, `message_delta {text}`, `done`. The UI appends/patches DOM on each event; no framework needed.
   - After resolution, the agent's final bubble summarizes: `✓ Root cause: beneficiary bank timed out (N66). Your ₹115.00 is auto-reversing per RBI T+1 — expected in your HDFC account by 2 Oct, 2:31 PM. I've raised ticket #PT-88214 and will notify you here. Anything else?`

5. **Input bar** (sticky bottom, white, hairline top): rounded input `Ask a question…` + violet send FAB (36px circle, paper-plane glyph). While agent is thinking: input disabled, replaced by shimmer `Sahayak is working…`.

### S6 — Passbook / Balance & History

Route `#/history`. Mirrors Paytm's "Balance & History".

1. Header: white, back, title `Balance & History`, right `⤓` download icon → toast `Statement download not available in demo`.
2. **Bank selector row**: `HDFC Bank ••4291` + `₹ 12,430.50` (Baloo 2, 18px) + chevron.
3. **Month section header**: `October 2026` (micro, ALL-CAPS, `--ink-3`, sticky).
4. **Txn rows** (white card list, 64px rows, hairline separators): 40px leading avatar — colored circle with initials (payee) or glyph; primary line `KIRANA STORE` (14px/600, caps for merchant, Title Case for people); secondary `UPI Ref No 4102345…` or `To kirana.store@ybl` (11.5px `--ink-3`); trailing amount (`- ₹115.00` red for debit, `+ ₹500.00` green for credit, 14px/600 mono digits) + timestamp `Today, 2:31 PM` (10.5px `--ink-3`). Status dot: 6px colored dot left of amount (green/amber/red). Failed rows additionally show a tiny `FAILED` micro-chip.
5. Tap row → S4. Data: `GET /api/txn` list (fixtures + live-created txns from the dev panel).

---

## 3. Demo Choreography

### 3.1 Three scripted scenarios

| Mode | Name | Pay outcome (S2e→S3) | Agent story (S5 tool timeline) | Resolution |
|---|---|---|---|---|
| **A** | Debited-not-credited | FAILURE, reason `Bank declined: switching timeout (N66)` | txn fetch → NPCI RRN check (DEBITED, credit NACK) → beneficiary bank verify → RBI T+1 rule → file ticket | Auto-reversal ETA + ticket #PT-88214 |
| **B** | Pending / SLA breach | PENDING | txn fetch → NPCI status PENDING → SLA clock check (38 min > 30 min SLA) → escalate to bank pipeline → monitor | Force-confirm: mid-chat a `tool_end` event flips the txn to SUCCESS (S4/S6 live-update), agent announces credit confirmed |
| **C** | Fraud / wrong payee | SUCCESS (payment goes through!) then user realizes | user taps "I didn't make this" chip → txn fetch → payee risk check (grievance-flagged VPA, 14 complaints) → RBI ombudsment escalation path → 3-step recovery checklist | Agent marks dispute, gives checklist + blocks payee |

All three end with a subtle "case closed" card in chat (green tick, ticket id, `Resolved by Sahayak AI · 1 min 42 sec` — the resolution timer is a demo flex; measure from agent-open to done).

### 3.2 The stage flow (3 scenes, ~4 minutes)

1. **Scene 1 — "It just works" (30s):** Home → Scan & Pay → amount ₹115 → PIN → SUCCESS. Judges see the app is real and complete.
2. **Scene 2 — "Then it breaks" (60s):** Presenter opens the **dev seed panel** (§3.3), taps `Mode A`, phone auto-navigates Home → pay flow again (pre-filled VPA `kirana.store@ybl`, presenter just types amount + PIN) → spinner hangs 3.5s → FAILURE screen. Presenter narrates the dread. Points at "Money debited… T+1" copy.
3. **Scene 3 — "Ask Sahayak" (2 min):** Tap the violet button → chat opens with case pre-loaded → presenter taps `Yes, investigate` → thinking card streams tool calls one-by-one (the money shot: film the phone, zoom later) → resolution bubble → presenter navigates to S4 to show the ticket reference now present, and in Mode B the status flips to green live.

### 3.3 "Seed a failure" dev panel

A slide-in drawer from the LEFT edge of the phone frame (so it reads as an injectable debug tool, not part of the app), toggled by:
- a tiny `⚡` tab on the frame's left rail (always visible to the presenter, hidden in "kiosk mode"), or
- keyboard ` (backquote).

Contents:
- 3 big buttons: `Mode A — Debited, not credited`, `Mode B — Pending > SLA`, `Mode C — Fraud / wrong payee`, plus `Reset demo` (clears created txns, restores fixture set).
- Options: amount preset (`₹115` / `₹1,150` / custom), payee preset (KIRANA STORE / fraudster@upi), tool-call pacing slider (0.5×–2×; default 1× ≈ 1.2s/step).
- Action: `POST /api/dev/seed {mode, amount, payee}` → returns `{txnId}` → UI closes drawer, routes `#/` then auto-starts S2 with the payee prefilled. The scenario mode is stored server-side on the session so `POST /api/pay` returns the mapped outcome and `POST /api/agent/open` streams the mapped tool script.

### 3.4 Fixture data (hardcoded in `/ui/src/data/fixtures.js`)

User: Arjun Rao, `arjun.r@paytm`, HDFC Bank `••4291`, balance ₹12,430.50. Payees: KIRANA STORE `kirana.store@ybl` (YESB0PTMUPI), FRAUDSTER `fraudster@upi`. History: 8 seeded rows (swiggy, jio recharge, rent, salary credit, kirana ×2, metro, friend) with realistic amounts (₹42, ₹239, ₹11,500, ₹48,000…) and statuses (mostly success, one old failed). RRNs: random 12-digit; UPI txn IDs: 12-digit.

---

## 4. Phone Frame Wrapper

The demo runs in a browser; wrap the app in a phone so desktop judges see a phone on screen.

```
┌──────────────── desktop stage (dark #0B1220, subtle radial glow) ───────────────┐
│                                                                                 │
│                        ┌── device bezel ────────────────┐                       │
│                        │  (rounded 54px, #1B2430,       │                       │
│                        │   12px black inset, 2px         │                      │
│                        │   #2A3546 highlight edge)       │                      │
│                        │  ┌── screen 390×844 ────────┐  │                       │
│                        │  │ status bar 44px          │  │                       │
│                        │  │ … app screens …          │  │                       │
│                        │  └──────────────────────────┘  │                       │
│                        └────────────────────────────────┘                       │
│              [side tab ⚡ dev panel]   [kiosk toggle]  [sound toggle]            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

- **Screen:** exactly 390×844 CSS px (iPhone-14-like), `overflow:hidden`, `border-radius: 40px` (inside bezel).
- **Notch:** a 126×32 black pill centered 8px from top, with a subtle time-text? No — keep the notch clean; time goes in the status bar.
- **Status bar (44px, rendered in-app so it can be transparent over the header gradient):** left = **live clock** `14:32` (updated via `setInterval(30s)`, 14px/600, system white/ink depending on screen), center = notch, right = signal bars + wifi + battery SVG glyphs (static, white over gradient, `--ink` over white screens).
- **Scaling:** `@media (max-height: 900px)` scale the whole stage with CSS `transform: scale()` (compute via JS: `scale = min(1, (vh−80)/920)`), centered flex.
- **Stage extras (outside the phone, HTML overlay):** app title `Sahayak — AI Payments Help (demo)`, small caption `Paytm Build for India · look-alike demo UI`, and the dev-panel tab hugging the bezel's left edge. All stage chrome hidden by **Kiosk mode** toggle (fullscreen phone + nothing else) for recording.
- On real mobile (viewport < 480px): drop the bezel, app fills the screen, status bar shows only the live clock.

---

## 5. Implementation Notes

### 5.1 Stack recommendation: **vanilla HTML/CSS/JS + lit-html-style template helpers (no build step)**

Rationale: 7 screens, one state machine, must run from a single static folder served by FastAPI. Zero build = zero CI risk at the finale. Use ES modules, `<template>` strings, and a ~60-line `h()`/render helper; hand-rolled router from `hashchange`. React only if the team strongly prefers it (then use Preact 10KB via CDN single-file, no bundler) — but vanilla is the recommendation.

### 5.2 File structure

```
sahayak-v2/
├── backend/                  # FastAPI (separate spec)
└── ui/
    ├── paytm-ui-spec.md      # THIS FILE
    └── src/
        ├── index.html        # phone frame + stage + <div id="app">
        ├── styles/
        │   ├── tokens.css    # §1 design tokens (custom properties)
        │   ├── base.css      # reset, typography, buttons, cards, keypad
        │   └── screens.css   # S1–S6 + frame + animations
        ├── app.js            # router, screen registry, screen-stack transitions
        ├── state.js          # simple store: {user, txns, currentTxn, agentSession}
        ├── api.js            # fetch wrappers + SSE subscribe
        ├── fixtures.js       # §3.4
        ├── components/       # keypad.js, txnRow.js, statusIcon.js,
        │                     # toolTimeline.js, chatBubble.js, phoneFrame.js
        ├── screens/
        │   ├── home.js  (S1)
        │   ├── pay.js   (S2 state machine incl. fake scanner)
        │   ├── status.js(S3 success/failure/pending)
        │   ├── txn.js   (S4)
        │   ├── chat.js  (S5 + SSE stream rendering)
        │   └── history.js(S6)
        └── assets/
            ├── fonts/        # self-hosted woff2 fallback
            └── sounds/       # tap.wav, success.wav, fail.wav (§6.3, optional)
```

### 5.3 Backend contract (FastAPI)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/pay/verify` | POST `{vpa}` → `{name, vpa, verified}` | S2b name verify (fixed table; `fraudster@upi` → "ONLINE SERVICES") |
| `/api/pay` | POST `{vpa, amount, pin?, scenario}` → `{status: success\|failure\|pending, txn}` | S2e outcome; server waits 2.5–4s; creates txn row |
| `/api/txn` / `/api/txn/:id` | GET | S4/S6 lists & detail (fixtures + created) |
| `/api/agent/open` | POST `{txnId}` → SSE stream | Opens case: emits `case`, first `message`, chips |
| `/api/agent/turn` | POST `{sessionId, text}` → SSE stream | Emits `tool_start`/`tool_end` ×N then `message_delta`s then `done` |
| `/api/dev/seed` | POST `{mode, amount, payee}` → `{txnId}` | Dev panel scenario seeding |

Serve `/ui/src` as static from FastAPI (`StaticFiles`) — one container, one port.

### 5.4 Animations — CSS only, no library

Total keyframes needed (~10): `slide-in-right` (screen push), `pop-in` (bubble), `check-draw` (stroke-dashoffset), `ring-pulse` ×2 (success), `spin` (spinner), `scan-line` (QR viewfinder), `shimmer` (thinking input), `pin-pop` (dot fill), `row-in` (timeline row), `settle` (failure icon). Respect `prefers-reduced-motion` (kill pulses/spins, keep state changes instant).

### 5.5 Thinking-view streaming: SSE (recommended) with polling fallback

- `EventSource('/api/agent/turn…')` — but SSE requires GET or POST-with-fetch-stream; simplest: `fetch` + `response.body.getReader()` on POST, parse `data:` lines (one tiny function). Fallback: 800ms polling of `GET /api/agent/session/:id/events?since=`. Implement SSE-first; polling is 15 extra lines.
- Timing server-driven (pacing slider scales sleeps server-side), so a network hiccup can't desync the show. Keep a **"fast mode" hotkey** (Shift+→) that asks the backend to compress remaining delays — a live-demo insurance policy.

### 5.6 Perf/constraints

No external CDN at runtime except Google Fonts (self-host for offline). Total JS < 40KB unminified. No images except sounds/fonts — everything else is CSS/SVG. Works in latest Chrome/Edge; that's all the finale needs.

---

## 6. What Makes It Feel REAL — the details list

1. **Indian rupee grouping:** format with `Intl.NumberFormat('en-IN')` → `₹1,15,000.00` (lakh grouping), never `115,000`. Amount input formats live as you type on the keypad.
2. **Currency symbol:** use `₹` (U+20B9), always prefixed with a thin space in list rows (`- ₹115.00`), no space in the big display (`₹115.00`).
3. **Verified payee names in ALL CAPS:** `KIRANA STORE`, `SWIGGY`; people in Title Case `Rahul Sharma` — this is how Paytm renders verified merchant names (approx).
4. **Mono digits for machine data:** RRN, UPI txn ID, VPA in JetBrains Mono; judges' eyes register "receipt authenticity".
5. **UPI PIN dots:** 6 circles that pop on fill; keypad auto-submit; label `Enter UPI PIN to pay ₹115.00`; never show digits; mask even in devtools (store only count, not value).
6. **Press states everywhere:** every tappable element scales to .96 within 80ms + brightness dip — the "haptic illusion". Add `navigator.vibrate?.(10)` on keypress.
7. **Sounds (optional, toggle on stage):** soft `tick` on keypad, rising two-note `ding` on success, low `thud` on failure. 3 tiny wavs, volume 0.25, mute toggle persisted in localStorage.
8. **Timestamps, human style:** `Today, 2:31 PM` / `Yesterday, 9:04 AM` / `1 Oct, 2:31 PM` in lists; full `1 Oct 2026, 2:31:04 PM` in S4. Live clock in the status bar.
9. **Copy tone:** short, status-first, RBI-anchored ("auto-reversed within T+1 as per RBI guidelines") — lifted from Paytm's own support language patterns (approx), never playful except the agent.
10. **The spinner copy:** `Do not press back or close the app` — the exact flavor of anxious microcopy real payment apps use.
11. **Partial-redaction account numbers:** `HDFC Bank ••4291` everywhere (use `••`, not `XX`).
12. **Truncated references in lists:** `UPI Ref No 4102345…` with full value + copy button in S4 (copy → toast `RRN copied`).
13. **Status color coding as a system:** same green/amber/red trio across S3 icon, S4 chip, S6 dot — consistency reads as production.
14. **Dev panel is honest chrome:** styled as a debug drawer, so judges who see it understand it's the demo harness, not a fake button in the app.
15. **Failed amount is red, pending is amber, but titles stay dark ink** — Paytm-style restraint: color signals, it doesn't shout.

---

## Appendix A — Research sources (consulted Oct 2026)

- Paytm brand colors (cyan `#00BAF2` / navy `#002E6E`–`#042E6F`): brandcolorcode.com, schemecolor.com, brandpalettes.com, logos-world.net
- Paytm failed/debited-not-credited copy & T+1/3–5 day refund language: paytm.com/support (UPI transaction failed; failed/pending resolution; wrong-UPI recovery pages)
- RRN / "UPI Ref No" 12-digit display in transaction details: paytm.com/support RRN & UTR pages; freo.money explainers
- 24x7 Help (phone/chatbot/email; 0120-4440-440): paytm.com/care/customer-care, paytm.com/contact-us
- Balance & History + statement download: paytm.com/support payment-history pages; ET/TOI coverage
- 2025 AI redesign (QR cinematic scan, calculator-on-pay-screen, Receive Money/Scan widgets, Total UPI Balance, Favourite Contacts, Hide Payments): Economic Times, Nov 2025; Electronic Payments International
- NPCI UPI PIN screen redesign (2025) and payee-verification-on-PIN-screen: LinkedIn UX write-ups (approx)

Everything marked (approx) is a best-effort visual match, not a verified Paytm spec.
