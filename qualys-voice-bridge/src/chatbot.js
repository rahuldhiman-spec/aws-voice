async function getChatbotReply(message) {
  return {
    reply: message ? `Echo: ${message}` : "",
    provider: "stub"
  };
}

module.exports = {
  getChatbotReply
};
