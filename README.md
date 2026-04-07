# AIPhoneAgentwithOpenAIRealtimeAPI

**OpenAI Realtime Voice Assistant with Twilio Integration**

This project demonstrates how to create an AI voice assistant that uses Twilio and the OpenAI Realtime API to handle phone calls in real time. The assistant is built using Python and FastAPI and is now tuned for a more natural, interruption-friendly Qualys support experience.

**Overview**

The code uses the following resources to function effectively:

Twilio's Python Guide: [Voice AI Assistant with OpenAI Realtime API]( https://www.twilio.com/en-us/blog/voice-ai-assistant-openai-realtime-api-python)

Twilio Python GitHub Repo Sample: [GitHub - Speech Assistant Sample](https://github.com/twilio-samples/speech-assistant-openai-realtime-api-python)

**Documentation Links**

Understanding the functionality of the code and the services it interacts with is crucial. Here are some useful documentation links:

Twilio Media Stream Events: [WebSocket Messages to Twilio](https://www.twilio.com/docs/voice/media-streams/websocket-messages)

Twilio Markup Language (TwiML): [TwiML Documentation](https://www.twilio.com/docs/voice/twiml)

OpenAI Realtime API: [OpenAI Realtime API Overview](https://platform.openai.com/docs/guides/realtime/overview)

OpenAI RealtimeEvents: [Realtime Events Documentation](https://platform.openai.com/docs/api-reference/realtime)

**Environment Variables**

For better security, secrets like `OPENAI_API_KEY` should be stored in an `.env` file.

1) Copy `.env.example` to `.env`
2) Set at least:

```
OPENAI_API_KEY=your_openai_api_key_here
PUBLIC_URL=https://your-domain.example/socket/invoke
```

`PUBLIC_URL` is strongly recommended for local development so Twilio gets a reachable `wss://.../media-stream` URL.

Optional variables you may want to set:

- `OPENAI_MODEL` (default: `gpt-realtime`)
- `OPENAI_WS_URL` (override the full Realtime WebSocket URL)
- `OPENAI_PROJECT`, `OPENAI_ORGANIZATION` for keys scoped to a specific project/org context
- `ASSISTANT_NAME`, `SUPPORT_PRODUCT`
- `VOICE` (default: `coral`), `SYSTEM_MESSAGE`, `AI_SPEAKS_FIRST`
- `INTERRUPT_DEBOUNCE_MS` to ignore tiny bursts of noise before interrupting speech
- `TRANSCRIPTION_MODEL`, `TRANSCRIPTION_LANGUAGE`, `TRANSCRIPTION_NOISE_REDUCTION` to tune phone-call transcription and noise handling
- `QUALYS_DYNAMIC_OPENERS` as a JSON array or `|`-separated list of rotating opener questions
- `KNOWLEDGE_BACKEND_URL` and related auth env vars to connect SearchUnify or another support-search backend
- `KNOWLEDGE_BACKEND_KIND` to force `searchunify_post` or `generic_get` if auto-detection is not enough
- `KNOWLEDGE_BACKEND_SSL_CERT_FILE`, `KNOWLEDGE_BACKEND_SSL_INSECURE`, and `KNOWLEDGE_CACHE_TTL_S` for enterprise TLS and caching control
- `SEARCHUNIFY_UID`, `SEARCHUNIFY_ACCESS_TOKEN`, `SEARCHUNIFY_SID`, `SEARCHUNIFY_COOKIE`, `SEARCHUNIFY_ORIGIN`, and `SEARCHUNIFY_REFERER` for SearchUnify POST-based search
- `LOG_LEVEL`, `LOG_OPENAI_EVENTS`, `SHOW_TIMING_MATH`
- `OPENAI_CONNECT_RETRIES`, `OPENAI_CONNECT_TIMEOUT_S`, `OPENAI_BETA_HEADER`
- `DEMO_LOOKUP_QUERY`, `DEMO_LOOKUP_PRODUCT_AREA` for the built-in demo probe endpoints

**Support Persona**

The default runtime persona is designed for a SearchUnify assistant that:

- clearly discloses it is an AI assistant on the opening line
- sounds warm, polished, confident, and natural without pretending to be human
- opens with a dynamic Qualys support question
- summarizes what it heard first and then says the Qualys issue framing out loud
- uses adaptive troubleshooting with confirmation loops and one-step-at-a-time guidance
- rephrases casual user wording into clearer Qualys terminology
- remembers important context across the call such as product area, issue summary, tried steps, and caller details
- handles interruptions, noise, and unclear speech more gracefully

**Phase 1 Interaction Upgrades**

The current app now includes:

- per-call memory tools so the assistant can remember issue summaries, tried steps, frustration level, and caller details
- transcript-driven issue-family routing across scans, VMDR, Cloud Agent, asset visibility, authentication, integrations, APIs, tags, and reporting
- live context hints that push the assistant toward better Qualys terminology and calmer de-escalation on future turns
- input transcription tuned for phone support calls with Qualys-specific vocabulary and near-field noise reduction

**Optional Knowledge Search**

If you configure `KNOWLEDGE_BACKEND_URL`, the assistant can expose a realtime function tool named `search_qualys_support_knowledge` and use your external support search backend during the call.

The app now supports two backend modes:

- `searchunify_post` for SearchUnify-style `POST /search/searchResultByPost` backends
- `generic_get` for simpler search endpoints that accept query params

If `KNOWLEDGE_BACKEND_KIND` is left blank, the app auto-detects `searchunify_post` when the URL contains `search/searchResultByPost`; otherwise it falls back to `generic_get`.

For SearchUnify-backed search, set:

```sh
KNOWLEDGE_BACKEND_URL=https://your-instance.searchunify.ai/search/searchResultByPost
KNOWLEDGE_BACKEND_NAME=SearchUnify
KNOWLEDGE_BACKEND_KIND=searchunify_post
SEARCHUNIFY_UID=...
SEARCHUNIFY_ACCESS_TOKEN=...
SEARCHUNIFY_SID=...
SEARCHUNIFY_ORIGIN=https://your-instance.searchunify.ai
SEARCHUNIFY_REFERER=https://your-instance.searchunify.ai/...
SEARCHUNIFY_COOKIE=
```

The SearchUnify adapter rewrites the caller query into stronger Qualys terminology, normalizes `result.hits`, ranks results by backend score, query overlap, product-area overlap, freshness, and solved status, and returns a `best_result`, `best_confidence`, `conflict`, and `response_mode` to help the model stay grounded.

For generic GET backends, the app expects:

- `q` for the search query
- `product_area` for an optional Qualys area hint
- `limit` for the max number of results

The backend should ideally return JSON with fields like `results`, `title`, `url`, and `snippet`, but the app includes normalization and lightweight ranking for common response shapes.

**How the Code Works**

**Setting Up a WebSocket**

The WebSocket is established between Twilio and OpenAI's Realtime API:

Starting a WebSocket: The websockets.connect() function is used to create a secure WebSocket connection to the OpenAI Realtime API. The Authorization and OpenAI-Beta headers are provided for authentication and to enable the beta features.

Sending Session Updates: Once the WebSocket is connected, session settings like audio formats, voice parameters, and instructions are sent to configure the conversation.

**Sending and Receiving Audio to Twilio**

Receiving from Twilio: The receive_from_twilio() function listens for audio data from Twilio's Media Stream. It extracts the audio payload from incoming messages and sends it to the OpenAI Realtime API.

Sending to Twilio: The send_to_twilio() function listens for responses from the OpenAI API. When audio data is received, it's encoded and sent back to Twilio in the required format.

Streaming Setup: The handle_media_stream WebSocket endpoint handles incoming audio from Twilio, connects to the OpenAI Realtime API, and ensures data flows between both services.

**Handling Interruptions**

The code handles interruptions gracefully:

When the caller starts speaking, the assistant's response is truncated to avoid overlap.

The current implementation adds a short debounce window before interruption so tiny bursts of noise do not cut off the assistant immediately. Clear speech still interrupts quickly.

**Getting Started**

Install Dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the Application:

```sh
python3 main.py
```

The server will run on `http://0.0.0.0:PORT` and expose:

- `GET /` basic status page
- `GET /health` health check
- `POST /incoming-call` Twilio webhook (returns TwiML)
- `WS /media-stream` Twilio Media Stream WebSocket

`GET /health` now also reports the active voice, assistant name, support product, transcription model, whether an external knowledge backend is enabled, the active backend kind, and the cache TTL.

**Production Deployment**

For your requested deployment shape, the app stays mounted internally at `/`, and Nginx publishes it at `/socket/invoke/`.

That means these public endpoints work:

- `https://your-domain.example/socket/invoke/incoming-call`
- `https://your-domain.example/socket/invoke/media-stream`
- `https://your-domain.example/socket/invoke/health`

Set:

```sh
PUBLIC_URL=https://your-domain.example/socket/invoke
```

The included Nginx example in `deploy/nginx/voice-agent.conf` uses:

```nginx
location /socket/invoke/ {
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /socket/invoke;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass http://127.0.0.1:3300/;
}
```

The trailing slash on `proxy_pass` is important because it strips `/socket/invoke/` before forwarding to the FastAPI app's internal routes like `/incoming-call` and `/media-stream`.
`X-Forwarded-Prefix` is included as a fallback so the app can still build the correct Twilio stream URL if `PUBLIC_URL` is missing.

**Docker Compose v3**

The repo now includes:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`

To run the app in a container:

```sh
docker compose up -d --build
```

The container listens on port `3300`, matching the Nginx upstream in `deploy/nginx/voice-agent.conf`.

To inspect health before pointing Twilio at it:

```sh
curl http://127.0.0.1:3300/health
curl "http://127.0.0.1:3300/demo-readiness?probe_search=true"
```

**Demo Readiness**

To de-risk the live demo, the app now exposes:

- `GET /demo-readiness` for a config checklist
- `GET /demo-readiness?probe_search=true` to run a live knowledge probe without placing a phone call
- `GET /demo-search?query=cloud%20agent%20not%20checking%20in&product_area=cloud%20agent` to inspect the grounded SearchUnify response directly

The readiness endpoint checks OpenAI config, `PUBLIC_URL`, active voice, knowledge backend mode, and SearchUnify-specific requirements.

If you copied the SearchUnify request from your browser, you can import it straight into `.env`:

```sh
pbpaste | python3 scripts/import_searchunify_curl.py
```

Or save the curl to a file and run:

```sh
python3 scripts/import_searchunify_curl.py --input-file /path/to/searchunify-curl.txt
```

That importer updates the SearchUnify-related `.env` keys automatically, including URL, UID, access token, SID, cookie, origin, referer, and search defaults.

For hot-reload during development:

```sh
uvicorn main:app --host 0.0.0.0 --port 5050 --reload --proxy-headers --forwarded-allow-ips="*"
```

**Debugging / Troubleshooting**

- Set `LOG_LEVEL=DEBUG` to get more detailed logs.
- Set `LOG_OPENAI_EVENTS=true` to log OpenAI event types.
- If Twilio can't connect to the WebSocket, confirm `PUBLIC_URL` is an HTTPS URL and that the generated stream URL starts with `wss://`.
- If you deploy behind Nginx at `/socket/invoke/`, keep `PUBLIC_URL` set to the full public base path, for example `https://your-domain.example/socket/invoke`.
- If you see `CERTIFICATE_VERIFY_FAILED` when connecting to OpenAI, ensure you installed dependencies (includes `certifi`), or set `OPENAI_SSL_CERT_FILE` to your corporate/root CA bundle.
- If you see `invalid_api_key`, verify the key is an active OpenAI Platform API key and, if it belongs to a specific project or org, set `OPENAI_PROJECT` / `OPENAI_ORGANIZATION` as well.
- If the voice sounds too flat or generic, set `VOICE=coral`, `VOICE=shimmer`, or another supported realtime voice in `.env`.
- If you wire in `KNOWLEDGE_BACKEND_URL`, use the `/health` endpoint to confirm the app reports `knowledge_backend_enabled: true`.
- Use `/demo-readiness?probe_search=true` before your demo so you can validate the retrieval path without making a live call.
- If your SearchUnify endpoint uses an enterprise or self-signed certificate chain, set `KNOWLEDGE_BACKEND_SSL_CERT_FILE` to the right CA bundle. For last-resort debugging only, set `KNOWLEDGE_BACKEND_SSL_INSECURE=true`.
- If SearchUnify lookups return no results, confirm `SEARCHUNIFY_UID`, `SEARCHUNIFY_ACCESS_TOKEN`, `SEARCHUNIFY_SID`, and any required `SEARCHUNIFY_COOKIE` / `SEARCHUNIFY_REFERER` values are set.
- If interruptions feel too eager or too slow, tune `INTERRUPT_DEBOUNCE_MS`.
- If speech recognition misses Qualys terms, adjust `TRANSCRIPTION_MODEL` or extend the transcription prompt in `main.py`.

**Set up ngrok so Twilio can access your local server**
![image](https://github.com/user-attachments/assets/510ecf96-ae94-4519-ab7d-6527f84df8b2)

Instructions on how to setup ngrok - [Ngrok Setup](https://ngrok.com/docs/getting-started/)


**Add your Url and /incoming-call endpoint to an Active number of your choosing in Twilio**
![image](https://github.com/user-attachments/assets/9e5b1235-bc3c-41f6-af4b-590bf36ff0eb)



**Example Replit Template**

You can easily fork and run this project on Replit using this link:

[Replit Template](https://replit.com/@AlozieIgbokwe2/OpenAI-Realtime-Assisstant)

Feel free to use and customize the template for your own project needs.
