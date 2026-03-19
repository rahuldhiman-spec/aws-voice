# qualys-voice-bridge

Minimal production-ready TypeScript scaffold for an AWS Lambda adapter that sits between Amazon Lex and an external SUVA API.

## Project layout

```text
.
|-- contracts/
|-- docs/
|-- lambda/
|   `-- adapter/
|       `-- handler.ts
|-- tests/
|-- .env.example
|-- eslint.config.mjs
|-- package.json
|-- tsconfig.json
`-- tsconfig.test.json
```

## What is included

- Strict TypeScript configuration
- ESLint with type-aware rules
- Prettier formatting
- Vitest with V8 coverage
- JSON Schemas for SUVA request and response payloads
- Generated TypeScript types derived from the schemas
- Ajv-based contract validation helpers
- A basic Lambda handler that accepts schema-validated SUVA request payloads
- Unit tests for contract mapping and payload validation

## Prerequisites

- Node.js 20+
- npm 10+

## Setup

```bash
npm install
cp .env.example .env
```

Update `.env` with the SUVA base URL that matches your environment.

If you change the SUVA schema files, regenerate the TypeScript types:

```bash
npm run generate:contracts
```

## Local verification

```bash
npm run lint
npm run format
npm run typecheck
npm run test
npm run build
```

Run everything in one pass:

```bash
npm run verify
```

## Lambda entry point

Build output is written to `dist/`. Deploy the handler at:

```text
dist/lambda/adapter/handler.handler
```

## Environment variables

| Variable          | Required | Description                                           |
| ----------------- | -------- | ----------------------------------------------------- |
| `SUVA_BASE_URL`   | No       | Base URL for the downstream SUVA API.                 |
| `AWS_REGION`      | No       | Standard AWS runtime region value.                    |
| `LOG_LEVEL`       | No       | Placeholder for structured logging configuration.     |

## Notes

- The handler expects a normalized `SuvaRequest` payload.
- Empty utterances are rejected before any downstream processing.
- The handler calls SUVA through `lambda/adapter/suva-client.ts`.
- SUVA transport failures, low confidence responses, and invalid downstream payloads are mapped to `ESCALATE`.
- The canonical SUVA contracts live in `contracts/*.schema.json`.
- Generated types are emitted to `contracts/suva.ts`.
- Runtime payload validation lives in `contracts/suva-validation.ts`.
