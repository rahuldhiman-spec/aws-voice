const test = require("node:test");
const assert = require("node:assert/strict");

const { runBridge } = require("../src/index");

test("runBridge exposes the project modules", async () => {
  const bridge = await runBridge();

  assert.equal(typeof bridge.transcribeAudio, "function");
  assert.equal(typeof bridge.synthesizeSpeech, "function");
  assert.equal(typeof bridge.getChatbotReply, "function");
  assert.equal(typeof bridge.connectCall, "function");
  assert.equal(typeof bridge.handoffCall, "function");
});
