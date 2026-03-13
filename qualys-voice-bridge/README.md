# qualys-voice-bridge

Node.js starter project for a voice bridge integration between Qualys-facing workflows and AWS voice services.

## Structure

```text
qualys-voice-bridge/
├── src/
│   ├── index.js
│   ├── transcribe.js
│   ├── polly.js
│   ├── chatbot.js
│   ├── connect.js
│   └── handoff.js
├── tests/
│   └── test-bridge.js
├── .env.example
├── .gitignore
├── package.json
└── README.md
```

## Getting Started

```bash
npm install
cp .env.example .env
npm test
```
