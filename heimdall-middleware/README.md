---
title: Heimdall Middleware
emoji: 🛡️
colorFrom: red
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# HEIMDALL Middleware

Dual-gateway prompt injection firewall. Gateway 1 (L1–L4 + agentic) screens input before it reaches an LLM; Gateway 2 (O2–O4 + agentic) screens output before it reaches the user. Streams layer-by-layer verdicts to the frontend over SSE.

Calls the `multi-llm-backend` Space internally for parallel LLM responses (Gemini, Groq, Mistral) — that Space must be deployed and running first.

## Endpoints

- `POST /chat` — run a prompt through both gateways
- `GET /stream/{session_id}` — SSE stream of layer-by-layer verdicts (open this *before* calling `/chat` with the same `session_id`)
- `POST /generate-attack` — returns a sample attack prompt for Red Team Mode
- `GET /stats` — aggregate detection stats
- `GET /health`

## Environment variables (set as Space secrets)

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | yes | |
| `GROQ_API_KEY` | yes | |
| `MISTRAL_API_KEY` | yes | |
| `MULTI_LLM_BACKEND_URL` | yes | Public URL of the `multi-llm-backend` Space, e.g. `https://your-username-heimdall-multi-llm-backend.hf.space` |
| `USE_FAKE_REDIS` | no | Defaults to `true` — no Redis server needed |
| `HF_TOKEN` | recommended | Avoids Hub rate limits when downloading the `all-MiniLM-L6-v2` embedding model on cold start |

## Cold start

This Space loads a ~80MB sentence-transformers model on startup (~60–90s). On the free CPU tier the Space sleeps after 48h of inactivity, so the first request after a long idle period will be slow while it wakes up and reloads the model. Visit the Space URL directly a minute before a live demo to warm it up.

See the main HEIMDALL deployment guide for full setup instructions.
