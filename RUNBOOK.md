# Runbook — QueueStorm Investigator

A step-by-step guide for cloning, configuring, running, validating, and
troubleshooting the service. Read this top to bottom on your first run.

---

## 0. Prerequisites

- **Python 3.10 or newer** (3.12 recommended for the Docker image)
- **pip** (latest)
- **Docker + Docker Compose** — only required for the production path
- **curl** — for smoke tests
- ~50 MB of free disk space (image + venv + sqlite)

Sanity check:

```bash
python3 --version     # >= 3.10
docker --version
docker compose version
```

---

## 1. Clone and configure

```bash
git clone <your-repo-url> queuestorm
cd queuestorm
```

Copy the environment template and edit if needed:

```bash
cp .env.example .env
# open .env — defaults work for local dev
```

The only field you **must** change for production is `SECRET_KEY`. Generate
a strong one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Paste it into `.env` as:

```
SECRET_KEY=<the-output>
```

---

## 2. Local dev (no Docker)

```bash
cd queuestorm
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

You should see Django's startup banner ending with
`Starting development server at http://0.0.0.0:8000/`.

### 2.1 Smoke test

In another terminal:

```bash
curl http://127.0.0.1:8000/health
# {"status": "ok"}
```

Open the UI:

| URL                              | Page                       |
| -------------------------------- | -------------------------- |
| <http://127.0.0.1:8000/dashboard/> | Dashboard with stat cards |
| <http://127.0.0.1:8000/submit/>    | Submit-a-ticket form      |
| <http://127.0.0.1:8000/tickets/>   | Ticket list + filters     |
| <http://127.0.0.1:8000/docs/>      | API docs page              |
| <http://127.0.0.1:8000/admin/>     | Django admin (optional)   |

To create an admin user:

```bash
python manage.py createsuperuser
```

### 2.2 Stopping the dev server

Foreground: `Ctrl+C`.
Background: `kill <pid>` or `pkill -f "manage.py runserver"`.

---

## 3. Production (Docker)

```bash
cd queuestorm
cp .env.example .env             # set SECRET_KEY, DEBUG=False, ALLOWED_HOSTS
docker compose up --build        # foreground
# or
docker compose up --build -d     # background (detached)
```

The image:

1. installs dependencies into the Python 3.12-slim base,
2. runs `python manage.py migrate --noinput` on container start,
3. serves gunicorn on `0.0.0.0:8000` with 3 workers.

### 3.1 Verify it is up

```bash
# Container status
docker compose ps

# Health
curl http://localhost:8000/health
# {"status": "ok"}

# Analyze a ticket
curl -s -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @sample_cases_smoke.json | python -m json.tool
```

`docker compose ps` should report `(healthy)` after a few seconds. The
healthcheck is `curl /health` every 30 s with 3 retries.

### 3.2 Logs

```bash
docker compose logs -f web          # follow
docker compose logs --tail=200 web  # last 200 lines
```

### 3.3 Stop, restart, rebuild

```bash
docker compose down            # stop + remove containers
docker compose restart web     # restart only the web service
docker compose up --build      # rebuild after a code change
```

The named volume `queuestorm-data` is **preserved** across `down`. To wipe it:

```bash
docker compose down -v
```

### 3.4 Connecting to a deployed endpoint

The judge harness expects a public URL. Easiest options:

- **Hosted platform** (Railway, Render, Fly.io) — push the repo, set env vars,
  expose the service port.
- **Local + tunnel** — run the container, then expose it with `cloudflared`,
  `ngrok http 8000`, or `tailscale serve`. The Dockerfile already binds
  `0.0.0.0:8000` so a tunnel can reach it.

---

## 4. Validating the engine

The repo ships a 3-case smoke set. The judge-provided set has 10 cases.

```bash
# Smoke (3 cases)
python manage.py run_sample_cases --file sample_cases_smoke.json

# Judge cases (10 cases)
python manage.py run_sample_cases --file SUST_Preli_Sample_Cases.json

# Strict mode — exit code 1 if any case fails
python manage.py run_sample_cases --file SUST_Preli_Sample_Cases.json --strict
```

Sample output:

```
[FAIL] SAMPLE-04 — case_type expected=payment_failed actual=wrong_transfer
[PASS] SAMPLE-01 — relevant_transaction_id ✓ evidence_verdict ✓ case_type ✓ department ✓
...
Total: 3   Passed: 2   Failed: 1
```

The command reads each `input`, calls `engine.analyzer.analyze()` directly
(no HTTP round-trip), and compares the output against the JSON's
`expected_output` block.

---

## 5. Inspecting data

SQLite lives at `db.sqlite3` locally or at `/app/data/db.sqlite3` in the
container (mounted on the `queuestorm-data` volume).

### 5.1 From the host

```bash
sqlite3 db.sqlite3 ".tables"
sqlite3 db.sqlite3 "SELECT id, ticket_id, case_type, severity, department FROM core_ticket ORDER BY id DESC LIMIT 10;"
```

### 5.2 From the container

```bash
docker compose exec web python manage.py dbshell
```

### 5.3 Via the Django admin

```bash
python manage.py createsuperuser   # local
docker compose exec web python manage.py createsuperuser   # container
```

Then visit `/admin/` and log in.

---

## 6. Adding migrations

After editing `core/models.py`:

```bash
python manage.py makemigrations core
python manage.py migrate
```

In the container, migrations run automatically on every `up`. To force a
re-migration on a deployed instance, restart the container:

```bash
docker compose restart web
```

---

## 7. Troubleshooting

### `Address already in use` on port 8000

Something else is bound. Find and stop it:

```bash
# Linux / WSL
sudo lsof -i :8000
sudo kill <pid>

# Or change the port
python manage.py runserver 0.0.0.0:8001
PORT=8001 docker compose up
```

### `ModuleNotFoundError: No module named 'django'`

You ran `python` outside the virtualenv.

```bash
source .venv/bin/activate
which python    # should be .../queuestorm/.venv/bin/python
```

### `OperationalError: no such table: core_ticket`

Migrations have not run.

```bash
python manage.py migrate
```

In Docker, the entrypoint script runs `migrate --noinput` automatically —
if you skipped it, rebuild the image or exec into the container:

```bash
docker compose exec web python manage.py migrate
```

### `KeyError: 'SECRET_KEY'` / `ImproperlyConfigured`

Your `.env` is missing. Copy the template:

```bash
cp .env.example .env
```

Or set the variable inline:

```bash
SECRET_KEY=dev-key python manage.py runserver
```

### Customer reply contains a phone number or asks for a PIN

The safety guardrail is doing its job. Inspect `engine/safety.py` and the
`BANNED_PHRASES` patterns. The reply templates in `engine/replies.py` should
never trigger the safety net; if one does, the template is the bug.

### Container exits immediately

```bash
docker compose logs web
```

Common causes:

- missing `.env` → `cp .env.example .env`
- bad `SECRET_KEY` with `DEBUG=False` → set a real one
- SQLite path not writable → check the volume mount in `docker-compose.yml`

### Engine returns `case_type: "other"` for a clear complaint

The keyword set in `engine/keywords.py` does not cover the wording. Add a
new keyword (in EN, BN, or Banglish), re-run the validator, and ensure the
new case still passes the other sample cases.

### Gunicorn workers time out

Default worker timeout is 60 s. If your case is genuinely taking longer,
raise it in `Dockerfile`:

```dockerfile
CMD ["sh", "-c", "python manage.py migrate --noinput && \
     gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} \
     --workers 3 --timeout 120 --access-logfile - --error-logfile -"]
```

---

## 8. Secret rotation

```bash
# 1. Generate a new key
NEW=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")

# 2. Replace SECRET_KEY in .env (local)
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$NEW|" .env

# 3. Replace it in your hosting platform's env-var config

# 4. Restart
docker compose restart web     # container
# or
# restart the platform service
```

Existing sessions/cookies signed with the old key will be invalidated —
acceptable for a stateless triage API.

---

## 9. Interpreting outputs

| Field                    | Possible values                                                                 |
| ------------------------ | ------------------------------------------------------------------------------- |
| `evidence_verdict`       | `consistent` / `inconsistent` / `insufficient_data`                             |
| `case_type`              | `payment_failed` / `wrong_transfer` / `refund` / `phishing` / `duplicate` / `agent_cash_in` / `merchant_settlement_delay` / `other` |
| `severity`               | `low` / `medium` / `high` / `critical`                                          |
| `department`             | `customer_support` / `dispute_resolution` / `fraud` / `merchant_ops` / `other`  |
| `human_review_required`  | `true` if the orchestrator escalated (phishing, dispute, critical, etc.)        |
| `confidence`             | 0.40–0.97 — heuristic, not calibrated                                           |
| `reason_codes`           | Short identifiers: `transaction_match`, `phishing_detected`, `prompt_injection_attempt`, … |

---

## 10. Submission checklist

Before pushing the final tag:

- [ ] `.env` is **not** committed (only `.env.example`).
- [ ] `db.sqlite3` is **not** committed.
- [ ] `*.md` is gitignored except `README.md` and `RUNBOOK.md`.
- [ ] `pip freeze` matches `requirements.txt` (or `pip install -r` works clean).
- [ ] `python manage.py run_sample_cases --file SUST_Preli_Sample_Cases.json --strict` exits 0.
- [ ] `docker compose up --build` boots cleanly and `/health` returns 200.
- [ ] `POST /analyze-ticket` returns 200 with a valid `customer_reply`.
- [ ] No stack traces in any error response.
- [ ] Private secrets (if any) are submitted through the official private
      submission field, **not** committed to the repo.
- [ ] GitHub repo is accessible to the organizers.

You're done. Good luck.
