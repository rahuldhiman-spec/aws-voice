async function transcribeAudio(audioStream) {
  return {
    transcript: "",
    source: audioStream || null
  };
}

module.exports = {
  transcribeAudio
};
