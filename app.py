"""Lead Triage API - classifies an inbound contact-form message with Claude
before it lands in an inbox (category, urgency, one-line summary).

Built to power the contact form on liamk02.github.io/silver-barnacle: the
form's JS calls POST /api/triage right before submitting to Formspree, and
includes the tags it gets back in the email. If this service is ever slow,
down, or rate-limited, the portfolio site still submits the plain form -
triage is a non-blocking enhancement, never a hard dependency.

Usage:
    python app.py
    (then POST to http://127.0.0.1:5000/api/triage)

Deployment (Render): set ANTHROPIC_API_KEY as a server-side environment
variable and run with gunicorn (see Procfile). Update ALLOWED_ORIGIN below
(or set it via env var) to the real portfolio domain before deploying.
"""

import json
import os
import re

import anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

MODEL = "claude-haiku-4-5"

# Only these origins may call the endpoint from a browser - without this, any
# site could embed a fetch() to this API and spend your Claude usage. Comma-
# separated so both the custom domain and its GitHub Pages fallback can be
# allowed at once (e.g. during a DNS cutover).
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGIN",
        "https://kvarzellconsulting.com,https://www.kvarzellconsulting.com,https://liamk02.github.io",
    ).split(",")
    if origin.strip()
}

MAX_MESSAGE_CHARS = 3000
MAX_NAME_CHARS = 200

CATEGORIES = ("client_lead", "collaboration", "networking", "general", "spam")
URGENCIES = ("low", "medium", "high")

SYSTEM_PROMPT = f"""You triage inbound messages from a contact form on an AI
consultant's portfolio site. Read the message and classify it.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{"category": "<one of {", ".join(CATEGORIES)}>", "urgency": "<one of {", ".join(URGENCIES)}>", "summary": "<one plain sentence, under 20 words, summarizing what they want>"}}

Category meanings:
- client_lead: someone describing a real business problem or asking about consulting/project work
- collaboration: proposing to work together, partnership, or joint project (not paying client work)
- networking: introducing themselves, connecting, no clear ask
- general: a question, feedback, or anything that doesn't fit above
- spam: unsolicited advertising, clearly automated, or irrelevant content

Urgency reflects only what's stated or implied in the message itself - a
stated deadline or "urgent" is high; a vague "someday" interest is low."""


def extract_json(text: str) -> dict:
    """Parse the model's JSON reply, tolerating stray text around it."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("No JSON object found in model response")


load_dotenv()
app = Flask(__name__)
client = anthropic.Anthropic()
limiter = Limiter(get_remote_address, app=app, default_limits=[])


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/health")
def health():
    # No Claude API call here - a liveness check should never cost money.
    response = jsonify({"status": "ok", "service": "lead-triage"})
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.route("/api/triage", methods=["POST", "OPTIONS"])
@limiter.limit("20 per hour")
def triage():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is empty."}), 400
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify({"error": f"Message too long (max {MAX_MESSAGE_CHARS} characters)."}), 400
    if len(name) > MAX_NAME_CHARS:
        return jsonify({"error": "Name too long."}), 400

    user_content = f"Name: {name or '(not given)'}\nMessage:\n{message}"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = next((b.text for b in response.content if b.type == "text"), "")
        tags = extract_json(raw)

        if tags.get("category") not in CATEGORIES or tags.get("urgency") not in URGENCIES:
            raise ValueError(f"Model returned unexpected values: {tags}")

    except anthropic.RateLimitError:
        return jsonify({"error": "Triage service busy - try again shortly."}), 429
    except anthropic.APIStatusError as e:
        return jsonify({"error": f"API error: {e.message}"}), 502
    except (ValueError, json.JSONDecodeError):
        # Model didn't return usable JSON - fail soft rather than 500, since
        # the caller treats triage as optional and shouldn't block on it.
        return jsonify({"error": "Could not classify this message."}), 502

    return jsonify({
        "category": tags["category"],
        "urgency": tags["urgency"],
        "summary": tags.get("summary", ""),
    })


@app.errorhandler(429)
def rate_limited(_e):
    return jsonify({"error": "Rate limit reached - try again in a bit."}), 429


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1", port=int(os.environ.get("PORT", 5000)))
