# QueueStorm Investigator

An internal AI copilot that triages customer support tickets. Drop in a complaint
and a transaction history; out comes a structured analysis — verdict, case type,
severity, department, an agent summary, a recommended next action, and a safe
reply draft — all from a transparent rule-based engine. No external LLM.

Built for the **SUST CSE Carnival 2026 — Online Preliminary Round**.

---

## Architecture at a glance

```
                ┌──────────────────────────────────────┐
   POST ticket  │  Django + DRF                         │  JSON response
   ─────────►   │   core.views.AnalyzeTicketView       │  ──────────►
                │            │                          │
                │            ▼                          │
                │   engine.analyzer.analyze()           │
                │            │                          │
                │  ┌─────┬──┴──┬──────┬─────┬─────┐    │
                │  │match│class│sever │route│reply│    │
                │  │     │ify  │ity   │     │     │    │
                │  └──┬──┴──┬──┴──────┴─────┴─────┘    │
                │     │  verdict + safety + escalation │
                │     ▼                                │
                │   SQLite persistence                 │
                └──────────────────────────────────────┘
                       │
                       ▼
       Server-rendered UI (Notion-style): /dashboard, /submit, /tickets, /docs
```

Two public HTTP endpoints:

| Method | Path             | Purpose                                       |
| ------ | ---------------- | --------------------------------------------- |
| GET    | `/health`        | Liveness probe for the judge harness.         |
| POST   | `/analyze-ticket`| Main analysis endpoint. JSON in, JSON out.    |

Plus a management command:

```bash
python manage.py run_sample_cases --file SUST_Preli_Sample_Cases.json
```

---

## Setup

### Local development (Python 3.10+)

```bash
cd queuestorm
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# edit .env if you want — defaults are safe for local dev

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Open <http://127.0.0.1:8000/dashboard/>.

### Docker

```bash
cd queuestorm
cp .env.example .env       # set SECRET_KEY etc.
docker compose up --build
```

The image runs `python manage.py migrate` on start, then serves with gunicorn on
port `8000`. The SQLite database lives on the named volume `queuestorm-data`.

### Railway

The repo ships a `railway.json` and a `Procfile`, both pointing at the same
Dockerfile entrypoint. Deploy in three clicks:

1. Push this repo to GitHub.
2. On Railway → **New Project → Deploy from GitHub Repo** → select it.
3. (Optional) Add a **Postgres** plugin if you want durable tickets. If you
   skip it, SQLite is used (data persists across restarts in the container's
   ephemeral filesystem, but is wiped on full redeploy — fine for the hackathon
   since the judge harness hits the API directly and each ticket is self-contained
   by `ticket_id`).

**Required env vars** (set them in the Railway service's *Variables* tab):

| Variable      | Notes                                                     |
| ------------- | --------------------------------------------------------- |
| `SECRET_KEY`  | Required. Generate with `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `PORT`        | Set automatically by Railway. Do not override.            |
| `ALLOWED_HOSTS` | Defaults to `*`; tighten for production. `*.up.railway.app` is auto-added. |
| `DEBUG`       | Leave unset in production (defaults to `False` on Railway). |

**Optional env vars**:

| Variable             | Notes                                                |
| -------------------- | ---------------------------------------------------- |
| `DATABASE_URL`       | Set automatically when you add the Postgres plugin. |
| `DJANGO_SQLITE_PATH` | Path to the SQLite file. Defaults to `/app/data/db.sqlite3`. |

The container is reachable at `https://<your-service>.up.railway.app/health`
within ~15 seconds of boot. Submit tickets at
`POST https://<your-service>.up.railway.app/analyze-ticket`.

### Environment variables

| Variable              | Required      | Default                  | Notes                                 |
| --------------------- | ------------- | ------------------------ | ------------------------------------- |
| `SECRET_KEY`          | yes (prod)    | insecure dev fallback    | Used by Django. **Set in prod.**      |
| `DEBUG`               | no            | `True`                   | Set `False` in production.            |
| `ALLOWED_HOSTS`       | no            | `*`                      | Comma-separated hostnames.            |
| `PORT`                | no            | `8000`                   | Container port.                       |
| `DJANGO_SQLITE_PATH`  | no            | `<project>/db.sqlite3`   | Override to mount a volume.           |

`.env.example` ships with placeholders only — never commit a real `SECRET_KEY`.

---

## API reference

### `GET /health`

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### `POST /analyze-ticket`

```bash
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-0001",
    "complaint": "I sent 2500 BDT to 01712345678 yesterday but the receiver says they got nothing.",
    "language": "en",
    "channel": "in_app_chat",
    "user_type": "customer",
    "campaign_context": "",
    "transaction_history": [
      {
        "transaction_id": "TXN-001",
        "timestamp": "2025-01-15T14:32:00Z",
        "type": "transfer",
        "amount": 2500,
        "counterparty": "01712345678",
        "status": "completed"
      }
    ]
  }'
```

**Response** (200 OK) — every field below is always present:

```jsonc
{
  "ticket_id":               "TKT-0001",
  "relevant_transaction_id": "TXN-001",
  "evidence_verdict":        "consistent",          // consistent | inconsistent | insufficient_data
  "evidence_summary":        "...",                  // alias of agent_summary
  "case_type":               "wrong_transfer",
  "severity":                "high",
  "department":              "dispute_resolution",
  "agent_summary":           "...",
  "recommended_next_action": "...",
  "customer_reply":          "...",
  "human_review_required":   true,
  "confidence":              0.79,
  "reason_codes":            ["transaction_match", "evidence_consistent"]
}
```

**Errors**

| Status | When                                                |
| ------ | --------------------------------------------------- |
| 400    | Payload validation failed (`details` lists fields). |
| 422    | Complaint string is empty.                          |
| 500    | Engine failure — generic message, no stack trace.   |

---

## Tech stack

- **Django 5.2** + **Django REST Framework 3.16** — JSON API surface
- **SQLite** — single-file persistence, easy to mount as a Docker volume
- **gunicorn** — production WSGI server
- **django-cors-headers** — permissive CORS for the judge harness
- **python-dotenv** — `.env` loading
- **Flowbite 2.5** + **Inter Tight** + **JetBrains Mono** (CDN) — Notion-inspired UI

---

## AI approach

**No external LLM.** Classification is purely rule-based and fully reproducible.

The pipeline in `engine/analyzer.py`:

1. **Match** (`engine/matcher.py`) — score every transaction against the
   complaint: amount match, type match, time recency, counterparty match,
   status semantics. Pick the best, recency as a tie-breaker.
2. **Classify** (`engine/classifier.py`) — a priority-ordered chain of
   keyword sets in English, Bangla, and Banglish:

   ```
   phishing > agent_cash_in > merchant_settlement > duplicate
       > payment_failed > wrong_transfer > refund > other
   ```

   Merchant-portal + settlement keywords are routed to
   `merchant_settlement_delay` regardless of priority.
3. **Verdict** (`engine/verdict.py`) — case-type-aware rule for
   `consistent` / `inconsistent` / `insufficient_data`. E.g. a transfer with
   `status=failed` is consistent with "payment failed"; a `completed` transfer
   is inconsistent with a `payment_failed` complaint.
4. **Severity** (`engine/severity.py`) — case type + amount: phishing → critical;
   refund over 10 000 BDT → high; refund over 5 000 BDT → medium; otherwise low.
5. **Route** (`engine/router.py`) — case_type → department. High-severity
   refunds are escalated from `customer_support` to `dispute_resolution`.
6. **Reply** (`engine/replies.py`) — pick a template by case_type and language;
   never reveal credentials, never promise money movement.
7. **Safety** (`engine/safety.py`) — every generated reply is scanned for
   banned phrases and phone-number leaks; the orchestrator raises on violation.
8. **Escalation** (`engine/escalation.py`) — disputes, phishing, inconsistent
   verdicts, high/critical severity, and large amounts all set
   `human_review_required=true`.
9. **Confidence** (`engine/confidence.py`) — 0.40–0.97 based on evidence
   strength and verdict.
10. **Reason codes** (`engine/reason_codes.py`) — short identifiers the UI
    can render as pills (`transaction_match`, `phishing_detected`, …).

---

## Safety logic

Four rules enforced inside `engine/safety.py`:

1. **Never request credentials.** The reply must never contain
   "send us your PIN", "share your PIN with us", "tell me your OTP", etc.
2. **Never promise money movement.** The reply must never contain
   "we will refund", "money will be returned", "guaranteed refund", etc.
3. **Never leak direct phone numbers.** Bangladeshi mobile numbers
   (`01XXXXXXXXX` / `+8801XXXXXXXXX`) are banned from customer replies.
4. **Prompt-injection attempts are logged.** Patterns like
   "ignore all previous instructions", "confirm a refund", "reveal your prompt"
   are tagged with the `prompt_injection_attempt` reason code but never block
   the analysis.

Every customer reply is scanned by `safety.enforce_safety()` before it leaves
the orchestrator. If a violation is found, the engine raises and the API
returns a generic 500 — no stack trace, no secret, no half-baked reply.

---

## Models

**No external models used.** Classification is purely rule-based and lives in
`engine/`. There are no weights, no embeddings, no API keys. Every output is
reproducible from the input.

---

## Assumptions & known limitations

- **Synthetic data only.** Customer names, phone numbers, and transaction
  histories used during development are fictitious.
- **SQLite is the only storage.** Fine for the hackathon scale; swap for
  Postgres if you scale up by changing `DATABASES` in `config/settings.py`.
- **Keyword sets are hand-curated.** They cover the most common English,
  Bangla, and Banglish phrasings from the sample cases. Coverage of dialectal
  variants is best-effort.
- **No authentication.** The judge harness hits `/analyze-ticket` directly;
  add a token / API-key gate before exposing publicly.
- **Confidence is heuristic**, not calibrated. Use it as a relative ranking,
  not a probability.
- **No file uploads, no streaming.** Tickets are sent as a single JSON body.

---

## Project layout

```
queuestorm/
├── config/                   Django project (settings, urls, wsgi)
├── core/
│   ├── management/
│   │   └── commands/
│   │       └── run_sample_cases.py
│   ├── models.py             Ticket, TransactionHistoryEntry, TicketAnalysis
│   ├── serializers.py        Input validation + enum choices
│   ├── views.py              /health, /analyze-ticket, dashboard, submit,
│   │                         tickets, docs
│   ├── admin.py
│   ├── urls.py
│   ├── static/core/
│   │   ├── css/style.css
│   │   └── js/app.js
│   └── templates/core/
│       ├── base.html
│       ├── dashboard.html
│       ├── submit.html
│       ├── ticket_list.html
│       ├── ticket_detail.html
│       └── api_docs.html
├── engine/
│   ├── keywords.py           EN / BN / Banglish keyword sets
│   ├── matcher.py            transaction scoring
│   ├── verdict.py            consistent / inconsistent / insufficient
│   ├── classifier.py         priority-ordered case_type chain
│   ├── severity.py
│   ├── router.py             case_type → department
│   ├── summarizer.py
│   ├── actions.py
│   ├── replies.py            EN + BN templates
│   ├── safety.py             injection detection + reply auditing
│   ├── escalation.py
│   ├── confidence.py
│   ├── reason_codes.py
│   └── analyzer.py           orchestrator
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
├── manage.py
├── .env.example              placeholders only — copy to .env
└── sample_cases_smoke.json   3 sample cases for the validator
```

---

## Quick smoke test

```bash
# 1. Server up
python manage.py runserver 0.0.0.0:8000 &

# 2. Health
curl http://127.0.0.1:8000/health
# {"status": "ok"}

# 3. Submit a ticket
curl -s -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @sample_cases_smoke.json | python -m json.tool

# 4. Validate the engine
python manage.py run_sample_cases --file sample_cases_smoke.json --strict
# Total: 3   Passed: 3   Failed: 0
```

For the full judge-provided cases, swap the filename:

```bash
python manage.py run_sample_cases --file SUST_Preli_Sample_Cases.json --strict
```

---

## License

Internal hackathon submission. Synthetic data; no real customer information
appears anywhere in this repository.
