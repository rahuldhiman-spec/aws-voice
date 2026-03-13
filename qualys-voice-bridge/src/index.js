const { transcribeAudio } = require("./transcribe");
const { synthesizeSpeech } = require("./polly");
const { getChatbotReply } = require("./chatbot");
const { connectCall } = require("./connect");
const { handoffCall } = require("./handoff");

async function runBridge() {
  return {
    transcribeAudio,
    synthesizeSpeech,
    getChatbotReply,
    connectCall,
    handoffCall
  };
}

if (require.main === module) {
  runBridge()
    .then(() => {
      process.stdout.write("qualys-voice-bridge initialized\n");
    })
    .catch((error) => {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 1;
    });
}

module.exports = {
  runBridge
};
