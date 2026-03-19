# SUVA Integration Requirements

This document is for the SUVA team.

Its purpose is simple:

- define exactly what the Lambda adapter needs from SUVA
- reduce avoidable `ESCALATE` responses
- make AWS call records and SUVA analytics line up through one correlation key

If SUVA meets the requirements below, this adapter will work reliably.

## 1. Summary

The adapter calls SUVA like this:

- Method: `POST`
- Path: `/voice/query`
- Content-Type: `application/json`
- Timeout budget: `2500ms`

If SUVA is slow, unreachable, returns non-JSON, or returns an invalid payload, the adapter will return:

```json
{
  "status": "ESCALATE"
}
```

If SUVA returns a confidence lower than `0.5`, the adapter will also force `ESCALATE`.

## 2. Request Contract SUVA Must Accept

SUVA must accept this exact JSON shape.

```json
{
  "sessionId": "session-123",
  "callerId": "+15551234567",
  "language": "en-US",
  "utterance": "Check my open findings",
  "metadata": {
    "awsContactId": "contact-123",
    "source": "amazon-connect-lex"
  }
}
```

### Required fields

- `sessionId`: string
- `callerId`: string
- `language`: string
- `utterance`: string
- `metadata.awsContactId`: non-empty string
- `metadata.source`: string

### Important request rules

- SUVA must accept `metadata.awsContactId` on every request.
- SUVA should treat `metadata.awsContactId` as the main correlation key for analytics and troubleshooting.
- SUVA should preserve `sessionId` and `awsContactId` in its own logs and metrics.
- SUVA should not depend on extra request properties not listed above.

## 3. Response Contract SUVA Must Return

SUVA must return valid JSON with this exact shape.

```json
{
  "status": "ANSWER",
  "replyText": "Here is your answer.",
  "voiceText": "Here is your answer.",
  "confidence": 0.92,
  "handoff": false,
  "caseId": "case-42",
  "reason": "OPTIONAL_REASON"
}
```

### Required fields

- `status`: one of `ANSWER`, `ESCALATE`, `RETRY`
- `replyText`: non-empty string
- `voiceText`: string
- `confidence`: number from `0` to `1`
- `handoff`: boolean

### Optional fields

- `caseId`: string
- `reason`: string

### Very important validation rules

- Response must be JSON, not plain text or HTML.
- Response must not contain unknown extra fields.
- `confidence` must stay within `0..1`.
- `replyText` must be present and non-empty.
- `voiceText` should be present. If it is blank or missing, the adapter will fall back to `replyText`.

## 4. Business Rules the Adapter Enforces

Even if SUVA returns HTTP `200`, the adapter will still force `ESCALATE` in these cases:

- SUVA response validation fails
- required fields are missing
- `confidence < 0.5`
- technical failure happens in the Lambda to SUVA call path

That means SUVA must satisfy both:

- transport success
- payload quality

Transport success alone is not enough.

## 5. Latency Requirement

SUVA must return within `2500ms`.

Why this matters:

- the adapter timeout is `2500ms`
- if SUVA crosses that limit, the adapter treats it as timeout and returns `ESCALATE`

Recommended target:

- p95 well below `2500ms`
- ideally p95 under `1500ms`

This leaves room for Lambda overhead and network variance.

## 6. HTTP Behavior SUVA Should Follow

Use HTTP status codes like this:

- `200`: SUVA processed the request and is returning a valid business response
- `4xx`: caller/request problem
- `5xx`: SUVA-side technical failure

Important:

- If SUVA wants the business result to be `ESCALATE` or `RETRY`, it should still return HTTP `200` with a valid response body.
- Non-2xx responses are treated by the adapter as technical failure, not business outcome.

## 7. Correlation Requirement

The correlation key is:

```text
awsContactId
```

This is used to map:

```text
AWS call <-> Lambda logs <-> SUVA analytics
```

SUVA must:

- ingest `metadata.awsContactId`
- store it in analytics
- log it in request tracing
- make it searchable in operations dashboards

Without this, support teams cannot reliably connect Amazon Connect activity to SUVA behavior.

## 8. Content Quality Requirement

For best voice experience, SUVA should return both:

- `replyText`: full written answer
- `voiceText`: shorter spoken answer

### What good `voiceText` looks like

- short
- direct
- easy to read aloud
- no markdown
- no links
- no long lists
- no extra filler

Example:

- `replyText`: `You have 3 open critical findings in production and 1 is overdue for remediation.`
- `voiceText`: `You have 3 open critical findings in production.`

If SUVA sends long or messy `voiceText`, the adapter will try to clean it, but SUVA should not rely on that cleanup as the main strategy.

## 9. Sensitive Data Guidance

The request contains `callerId`, which is sensitive.

SUVA should:

- treat `callerId` as sensitive data
- avoid echoing it back in response fields
- avoid putting it into analytics dimensions unless strictly required

The preferred correlation field is `awsContactId`, not `callerId`.

## 10. What Causes Bad User Experience

These are the most common ways SUVA can make the adapter look broken:

- response arrives after `2500ms`
- response is not valid JSON
- missing `replyText`
- confidence outside `0..1`
- confidence below `0.5`
- unexpected extra response properties
- long, messy, link-heavy `voiceText`
- not recording `awsContactId` in SUVA analytics

## 11. SUVA Acceptance Checklist

SUVA integration is ready when all of these are true:

- `POST /voice/query` is reachable from Lambda
- SUVA accepts the request schema exactly as defined
- SUVA returns valid JSON only
- SUVA returns the required fields on every `200` response
- SUVA keeps `confidence` in `0..1`
- SUVA returns in under `2500ms`
- SUVA uses `awsContactId` as a searchable correlation field
- SUVA provides short voice-friendly `voiceText`
- SUVA uses HTTP `200` for business outcomes and `5xx` for technical failures

## 12. Recommended Example Responses

### Good answer

```json
{
  "status": "ANSWER",
  "replyText": "You have 3 open critical findings in production and 1 is overdue.",
  "voiceText": "You have 3 open critical findings in production.",
  "confidence": 0.91,
  "handoff": false
}
```

### Good business escalate

```json
{
  "status": "ESCALATE",
  "replyText": "I need to connect you to a human agent for that request.",
  "voiceText": "Let me connect you to a human agent.",
  "confidence": 0.88,
  "handoff": true,
  "reason": "HUMAN_REVIEW_REQUIRED"
}
```

### Bad response example

This will fail adapter validation:

```json
{
  "status": "ANSWER",
  "confidence": 1.2,
  "handoff": false
}
```

Why it fails:

- `replyText` is missing
- `voiceText` is missing
- `confidence` is outside `0..1`

## 13. Final Requirement in One Sentence

To work perfectly with this adapter, SUVA must return a valid, fast, voice-friendly JSON response for `POST /voice/query`, keep `confidence >= 0.5` for usable answers, and always use `metadata.awsContactId` as the shared correlation key.
