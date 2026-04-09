# Qualys WebRTC Voice Demo

Browser-first Qualys support demo built on the OpenAI Realtime API, FastAPI, and SearchUnify grounding.

The old phone-call media bridge is gone. The browser now connects directly to OpenAI over WebRTC, while the FastAPI app serves:

- the desktop demo UI
- SearchUnify-backed grounding tools
- per-session call memory
- health and demo-readiness endpoints

## What the app does

- opens a direct WebRTC session from the browser to the OpenAI Realtime API
- keeps the conversation voice-first with live caller and assistant transcript panels
- preserves Qualys support context across turns with backend memory tools
- grounds exact troubleshooting, error details, API facts, and integration questions with SearchUnify when the model decides it needs them
- exposes a polished desktop-first demo interface instead of a phone-call flow

## Important development note

This version intentionally exposes a long-lived OpenAI API key to the browser because that is what the demo currently wants.

That is acceptable only for development or tightly controlled demos.

For production, use the OpenAI-recommended short-lived auth flow instead of shipping a long-lived key to the client.

Official OpenAI references used for this migration:

- Realtime API reference: https://platform.openai.com/docs/api-reference/realtime
- Realtime conversations guide: https://platform.openai.com/docs/guides/realtime-model-capabilities

## Runtime shape

Browser:

- captures microphone audio
- creates the WebRTC peer connection
- sends and receives Realtime events on the data channel
- handles model tool calls in the browser and forwards them to the FastAPI backend

FastAPI backend:

- serves `/` and `/static/*`
- returns browser session config from `/api/realtime-config`
- stores session memory through `/api/tool/remember-context` and `/api/tool/get-context`
- runs SearchUnify lookups through `/api/tool/search`

## Key endpoints

- `GET /`
- `GET /health`
- `GET /api/realtime-config`
- `POST /api/session/reset`
- `POST /api/context/transcript`
- `POST /api/tool/remember-context`
- `POST /api/tool/get-context`
- `POST /api/tool/search`
- `GET /demo-readiness`
- `GET /demo-search`

## Environment variables

Required:

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-realtime
VOICE=alloy
ASSISTANT_NAME=Aira
SUPPORT_PRODUCT=Qualys
```

Common UI and session settings:

```env
PORT=3300
PUBLIC_URL=https://your-domain.example/socket/invoke
AI_SPEAKS_FIRST=true
TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
TRANSCRIPTION_LANGUAGE=en
TRANSCRIPTION_NOISE_REDUCTION=near_field
SERVER_VAD_THRESHOLD=0.62
SERVER_VAD_PREFIX_PADDING_MS=300
SERVER_VAD_SILENCE_DURATION_MS=450
```

SearchUnify grounding:

```env
KNOWLEDGE_BACKEND_URL=https://your-instance.searchunify.ai/search/searchResultByPost
KNOWLEDGE_BACKEND_NAME=SearchUnify
KNOWLEDGE_BACKEND_KIND=searchunify_post
SEARCHUNIFY_UID=...
SEARCHUNIFY_ACCESS_TOKEN=...
SEARCHUNIFY_SID=...
SEARCHUNIFY_ORIGIN=https://your-instance.searchunify.ai
SEARCHUNIFY_REFERER=https://your-instance.searchunify.ai/...
SEARCHUNIFY_COOKIE=...
SEARCHUNIFY_RESULTS_PER_PAGE=10
```

Optional search/debug settings:

```env
KNOWLEDGE_RESULT_LIMIT=5
KNOWLEDGE_CACHE_TTL_S=180
KNOWLEDGE_BACKEND_TIMEOUT_S=8
KNOWLEDGE_BACKEND_SSL_INSECURE=true
DEMO_LOOKUP_QUERY=qualys cloud agent not checking in
DEMO_LOOKUP_PRODUCT_AREA=cloud agent
LOG_LEVEL=info
```

## Local development

```sh
cd aws-voice
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Open:

```sh
http://127.0.0.1:3300/
```

## Docker

```sh
cd aws-voice
docker compose up -d --build --force-recreate
```

The compose file mounts `main.py`, `static/`, `.env`, and `README.md` into the container for fast iteration.

## Demo checks

Readiness:

```sh
curl http://127.0.0.1:3300/health
curl "http://127.0.0.1:3300/demo-readiness?probe_search=true"
```

Direct SearchUnify probe:

```sh
curl "http://127.0.0.1:3300/demo-search?query=cloud%20agent%20not%20checking%20in&product_area=cloud%20agent"
```

## SearchUnify helper

If you copied a SearchUnify request from your browser, you can still import it into `.env` with:

```sh
pbpaste | python3 scripts/import_searchunify_curl.py
```

Or:

```sh
python3 scripts/import_searchunify_curl.py --input-file /path/to/searchunify-curl.txt
```

## Reverse proxy example

The included Nginx config keeps the app mounted internally at `/` and publishes it externally at `/socket/invoke/`.

That means the UI and API become available at paths like:

- `https://your-domain.example/socket/invoke/`
- `https://your-domain.example/socket/invoke/health`
- `https://your-domain.example/socket/invoke/api/realtime-config`

## Production note

If you take this beyond demo usage, the first thing to change is browser auth. Keep the UI, tool loop, and SearchUnify wiring, but replace the long-lived browser API key with a short-lived session or server-mediated auth flow.
