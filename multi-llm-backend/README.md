---
title: Heimdall Multi LLM Backend
emoji: 🔀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Multi-LLM Backend

Internal API that fans a single prompt out to three LLM providers in parallel (Gemini, Groq, Mistral) with lazy fallback. Called by the `heimdall-middleware` Space — not meant to be used standalone.

## Endpoints

- `POST /chat` — send `{"message": "...", "session_id": "..."}`, returns parallel responses from all three providers
- `GET /health` — provider key status
- `GET /stats` — request counters

## Environment variables (set as Space secrets)

| Variable | Required |
|---|---|
| `GEMINI_API_KEY` | yes |
| `GROQ_API_KEY` | yes |
| `MISTRAL_API_KEY` | yes |

See the main [HEIMDALL deployment guide] for full setup instructions.
