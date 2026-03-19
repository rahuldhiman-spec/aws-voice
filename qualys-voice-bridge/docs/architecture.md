# Voice Adapter Architecture

This scaffold assumes the following request path:

1. Amazon Connect routes a caller to Lex.
2. Lex or an upstream normalization layer invokes the Lambda adapter.
3. The adapter validates the incoming SUVA-shaped request contract.
4. The adapter calls the downstream SUVA `/voice/query` endpoint.
5. The adapter returns the SUVA response or escalates when the downstream result is unsafe to use.

The current implementation is intentionally small:

- No UI, RAG, or case logic is included.
- SUVA request and response payloads are defined as JSON Schema and validated at runtime before use.
- The handler currently accepts a normalized `SuvaRequest` payload rather than a raw Lex event.
- Empty utterances are rejected with a request validation error.
- SUVA failures, invalid downstream payloads, and low-confidence answers are converted into `ESCALATE` responses.
