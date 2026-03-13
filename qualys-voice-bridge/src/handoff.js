async function handoffCall(target = "agent") {
  return {
    handedOff: true,
    target
  };
}

module.exports = {
  handoffCall
};
