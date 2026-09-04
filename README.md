# Lead Triage API

A tiny API that classifies an inbound contact-form message with Claude
before it lands in an inbox - category (client lead / collaboration /
networking / general / spam), urgency, and a one-line summary.

Built to power the contact form on
[my portfolio site](https://kvarzellconsulting.com/): the form's
JS calls this API right before submitting to Formspree, and includes the
tags in the email. If this service is ever slow, down, or rate-limited, the
form still submits normally - triage is a non-blocking enhancement layered
on top, never a hard dependency for the contact form to work.

## Why this exists

Most of my other project (`doc-qa-tool`) is retrieval: search documents,
answer from what's found. This one is a different core technique -
**structured extraction**: turn free text into a fixed set of tags a
program can act on. That pattern (classify, score, extract fields) shows up
constantly in real consulting work - lead scoring, support-ticket routing,
sentiment tagging - more often, in practice, than document search does.

## How it works

1. `POST /api/triage` with `{"name": "...", "message": "..."}`
2. Claude (Haiku 4.5 - cheap, fast, exactly suited to short classification)
   reads the message and returns JSON: `category`, `urgency`, `summary`
3. The response is parsed defensively (tolerates the model wrapping the
   JSON in a sentence) and validated against a fixed set of allowed values
   before being trusted

## Guardrails (public endpoint)

- **CORS-restricted** - only requests from an origin in `ALLOWED_ORIGIN`
  (comma-separated; the portfolio site's domain(s)) are permitted from a browser
- **Rate limited** - 20 requests/hour per caller (`flask-limiter`)
- **Input validated** - oversized messages rejected before reaching Claude
- **Cheap model** - Haiku 4.5, chosen for classification specifically

## Local setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env, paste in your Anthropic API key
python app.py
```

## Deploy to Render (free tier)

1. Push this repo to GitHub
2. New Web Service on [render.com](https://render.com), pointed at this repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app` (the `Procfile` sets this too)
5. Environment variables: `ANTHROPIC_API_KEY` (required), `ALLOWED_ORIGIN`
   (optional - defaults to the portfolio's real domain already)

Set a monthly spend cap in the Anthropic Console regardless - same reasoning
as `doc-qa-tool`: this is a public endpoint, and rate limiting bounds normal
traffic but a cap is the real safety net.
