async function connectCall(callContext = {}) {
  return {
    connected: true,
    callContext
  };
}

module.exports = {
  connectCall
};
