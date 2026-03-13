async function synthesizeSpeech(text, voiceId = process.env.POLLY_VOICE_ID || "Joanna") {
  return {
    audioStream: null,
    text,
    voiceId
  };
}

module.exports = {
  synthesizeSpeech
};
