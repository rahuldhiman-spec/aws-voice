const state = {
  config: null,
  health: null,
  pc: null,
  dataChannel: null,
  localStream: null,
  remoteStream: null,
  sessionId: null,
  isConnected: false,
  isConnecting: false,
  isDisconnecting: false,
  assistantSpeaking: false,
  interruptTimer: null,
  processedCallIds: new Set(),
  processedTranscriptItemIds: new Set(),
  activeResponseId: null,
  pendingResponseCreate: false,
};

const refs = {
  eyebrowLabel: document.getElementById("eyebrowLabel"),
  heroText: document.getElementById("heroText"),
  callSurface: document.getElementById("callSurface"),
  connectButton: document.getElementById("connectButton"),
  buttonLabel: document.getElementById("buttonLabel"),
  callHint: document.getElementById("callHint"),
  remoteAudio: document.getElementById("remoteAudio"),
};

const appBaseUrl = new URL(".", window.location.href);

function buildAppUrl(path) {
  return new URL(String(path || "").replace(/^\/+/, ""), appBaseUrl).toString();
}

const routes = {
  health: buildAppUrl("health"),
  transcript: buildAppUrl("api/context/transcript"),
  rememberContext: buildAppUrl("api/tool/remember-context"),
  getContext: buildAppUrl("api/tool/get-context"),
  search: buildAppUrl("api/tool/search"),
  realtimeCall: buildAppUrl("api/realtime-call"),
  sessionReset: buildAppUrl("api/session/reset"),
  realtimeConfig: buildAppUrl("api/realtime-config"),
};

function generateSessionId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function trimText(value, limit = 180) {
  const clean = String(value || "").trim().replace(/\s+/g, " ");
  return clean.length <= limit ? clean : `${clean.slice(0, limit - 1)}…`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json();
}

function parseJsonSafe(value, fallback = {}) {
  if (typeof value !== "string" || !value.trim()) {
    return fallback;
  }
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function sendRealtimeEvent(event) {
  if (!state.dataChannel || state.dataChannel.readyState !== "open") {
    return;
  }
  state.dataChannel.send(JSON.stringify(event));
}

function flushPendingResponseCreate() {
  if (!state.pendingResponseCreate || state.assistantSpeaking) {
    return;
  }
  state.pendingResponseCreate = false;
  sendRealtimeEvent({
    type: "response.create",
    response: {
      output_modalities: ["audio"],
    },
  });
}

function clearInterruptTimer() {
  if (!state.interruptTimer) {
    return;
  }
  window.clearTimeout(state.interruptTimer);
  state.interruptTimer = null;
}

function scheduleAssistantInterrupt() {
  if (!state.assistantSpeaking || state.interruptTimer) {
    return;
  }

  const debounceMs = Number(state.config?.interrupt_debounce_ms ?? 180);
  state.interruptTimer = window.setTimeout(() => {
    state.interruptTimer = null;
    if (!state.assistantSpeaking) {
      return;
    }
    sendRealtimeEvent({ type: "response.cancel" });
  }, Math.max(0, debounceMs));
}

function getFunctionCallsFromResponse(event) {
  const output = event?.response?.output;
  if (!Array.isArray(output)) {
    return [];
  }
  return output.filter((item) => item?.type === "function_call" && item?.call_id && item?.name);
}

function setHint(text, tone = "neutral") {
  refs.callHint.textContent = text;
  refs.callHint.dataset.tone = tone;
}

function setActivity(activity = "idle") {
  refs.callSurface.dataset.activity = activity;
}

function setUiState(mode) {
  document.body.dataset.callState = mode;
  refs.callSurface.dataset.state = mode;

  if (mode === "connecting") {
    refs.connectButton.disabled = true;
    refs.buttonLabel.textContent = "Connecting...";
    return;
  }

  refs.connectButton.disabled = false;

  if (mode === "live") {
    refs.buttonLabel.textContent = "End Call";
    return;
  }

  if (mode === "error") {
    refs.buttonLabel.textContent = "Try Again";
    return;
  }

  refs.buttonLabel.textContent = "Start Call";
}

function logEvent(message) {
  console.info(`[voice-ui] ${message}`);
}

function applyBranding(data) {
  if (!data) {
    return;
  }

  if (data.support_product) {
    refs.eyebrowLabel.textContent = `${data.support_product} Voice Experience`;
  }

  if (data.assistant_name) {
    refs.heroText.textContent = `${data.assistant_name} is ready for a live browser-based support call with a single-click launch.`;
    setHint(`Allow microphone access when prompted to start the call with ${data.assistant_name}.`);
  }
}

async function syncTranscriptContext(transcript) {
  if (!state.sessionId) {
    return null;
  }

  try {
    return await fetchJson(routes.transcript, {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        transcript,
      }),
    });
  } catch (error) {
    logEvent(`Transcript sync failed: ${trimText(error.message || String(error), 120)}`);
    return null;
  }
}

function sendSystemMessage(text) {
  const message = String(text || "").trim();
  if (!message) {
    return;
  }

  sendRealtimeEvent({
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "system",
      content: [{ type: "input_text", text: message }],
    },
  });
}

async function autoGroundAndRespond(transcript) {
  if (state.assistantSpeaking) {
    // Cancel and wait for response.done before creating a new response.
    state.pendingResponseCreate = true;
    sendRealtimeEvent({ type: "response.cancel" });
  }

  const contextPayload = await syncTranscriptContext(transcript);
  const systemHint = String(contextPayload?.system_hint || "").trim();
  if (systemHint) {
    sendSystemMessage(systemHint);
  }

  const shouldGround = Boolean(
    contextPayload?.search_recommended && state.config?.knowledge_backend_enabled
  );

  if (shouldGround) {
    try {
      const grounding = await fetchJson(routes.search, {
        method: "POST",
        body: JSON.stringify({
          session_id: state.sessionId,
          query: transcript,
          product_area: "",
        }),
      });

      const answerContext = String(grounding?.answer_context || "").trim();
      const bestTitle = String(grounding?.best_result?.title || "").trim();
      const bestConfidence = Number(grounding?.best_confidence ?? 0);
      const header = bestTitle
        ? `Grounding: SearchUnify top hit "${bestTitle}" (confidence ${bestConfidence}).`
        : "Grounding: SearchUnify results.";
      const groundingText = answerContext ? `${header}\n${answerContext}` : header;

      sendSystemMessage(
        `${groundingText}\nUse this grounding when answering. Do not call the search tool again unless the user asks for more details.`
      );
    } catch (error) {
      logEvent(`Auto-grounding failed: ${trimText(error.message || String(error), 120)}`);
    }
  }

  state.pendingResponseCreate = true;
  flushPendingResponseCreate();
}

async function invokeTool(name, args) {
  if (!state.sessionId) {
    return { ok: false, error: "Session is not initialized." };
  }

  try {
    if (name === "remember_call_context") {
      return await fetchJson(routes.rememberContext, {
        method: "POST",
        body: JSON.stringify({
          session_id: state.sessionId,
          payload: args || {},
        }),
      });
    }

    if (name === "get_call_context") {
      return await fetchJson(routes.getContext, {
        method: "POST",
        body: JSON.stringify({
          session_id: state.sessionId,
        }),
      });
    }

    if (name === "search_bluebeam_support_knowledge") {
      return await fetchJson(routes.search, {
        method: "POST",
        body: JSON.stringify({
          session_id: state.sessionId,
          query: String(args?.query || ""),
          product_area: args?.product_area || "",
        }),
      });
    }
  } catch (error) {
    return { ok: false, error: error.message || String(error) };
  }

  return { ok: false, error: `Unknown tool: ${name}` };
}

async function handleFunctionCalls(event) {
  const calls = getFunctionCallsFromResponse(event);
  if (!calls.length) {
    return;
  }

  for (const call of calls) {
    if (state.processedCallIds.has(call.call_id)) {
      continue;
    }

    state.processedCallIds.add(call.call_id);
    const args = parseJsonSafe(call.arguments, {});
    const output = await invokeTool(call.name, args);

    sendRealtimeEvent({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: call.call_id,
        output: JSON.stringify(output),
      },
    });
  }

  sendRealtimeEvent({ type: "response.create" });
}

async function handleRealtimeEvent(event) {
  if (!event?.type) {
    return;
  }

  switch (event.type) {
    case "input_audio_buffer.speech_started":
      setActivity("user");
      scheduleAssistantInterrupt();
      break;
    case "input_audio_buffer.speech_stopped":
      clearInterruptTimer();
      setActivity("live");
      break;
    case "response.created":
      state.assistantSpeaking = true;
      state.activeResponseId = String(event.response?.id || "") || null;
      setActivity("assistant");
      break;
    case "response.done":
      state.assistantSpeaking = false;
      state.activeResponseId = null;
      clearInterruptTimer();
      setActivity("live");
      await handleFunctionCalls(event);
      flushPendingResponseCreate();
      break;
    case "conversation.item.input_audio_transcription.completed": {
      const transcript = String(event.transcript || "").trim();
      if (transcript) {
        const itemId = String(event.item_id || "");
        if (itemId && state.processedTranscriptItemIds.has(itemId)) {
          break;
        }
        if (itemId) {
          state.processedTranscriptItemIds.add(itemId);
        }
        await autoGroundAndRespond(transcript);
      }
      break;
    }
    case "error": {
      const message = trimText(event.error?.message || "Unknown Realtime error", 140);
      if (message.toLowerCase().includes("response.cancel")) {
        logEvent(`Ignored interrupt race: ${message}`);
        state.assistantSpeaking = false;
        clearInterruptTimer();
        setActivity("live");
        break;
      }
      logEvent(`Realtime error: ${message}`);
      await disconnect({
        resetSession: false,
        reason: "error",
        message,
      });
      break;
    }
    default:
      break;
  }
}

async function createRealtimeCall(offerSdp) {
  const response = await fetch(routes.realtimeCall, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ sdp: offerSdp }),
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    let detail = await response.text();
    if (contentType.includes("application/json")) {
      const payload = parseJsonSafe(detail, null);
      detail = payload?.detail || detail;
    }
    throw new Error(detail || `OpenAI create call failed with ${response.status}`);
  }

  const sdp = await response.text();
  if (!sdp) {
    throw new Error("Backend returned an empty SDP answer.");
  }
  return sdp;
}

function stopTracks(stream) {
  for (const track of stream?.getTracks?.() || []) {
    track.stop();
  }
}

async function disconnect({ resetSession = true, reason = "ended", message = "" } = {}) {
  if (state.isDisconnecting) {
    return;
  }

  state.isDisconnecting = true;
  state.isConnecting = false;

  try {
    if (resetSession && state.sessionId) {
      await fetchJson(routes.sessionReset, {
        method: "POST",
        body: JSON.stringify({ session_id: state.sessionId }),
      });
    }
  } catch (error) {
    logEvent(`Session reset failed: ${trimText(error.message || String(error), 120)}`);
  }

  const dataChannel = state.dataChannel;
  const peerConnection = state.pc;
  const localStream = state.localStream;
  const remoteStream = state.remoteStream;

  state.dataChannel = null;
  state.pc = null;
  state.localStream = null;
  state.remoteStream = null;
  state.sessionId = null;
  state.isConnected = false;
  state.assistantSpeaking = false;
  state.activeResponseId = null;
  state.pendingResponseCreate = false;
  state.processedCallIds.clear();
  state.processedTranscriptItemIds.clear();
  clearInterruptTimer();

  try {
    dataChannel?.close();
  } catch {}

  try {
    peerConnection?.close();
  } catch {}

  stopTracks(localStream);
  stopTracks(remoteStream);
  refs.remoteAudio.srcObject = null;

  setActivity("idle");

  if (reason === "error") {
    setUiState("error");
    setHint(message || "Could not start the call. Try again.", "error");
  } else {
    setUiState("idle");
    setHint(message || "Allow microphone access when prompted.", "neutral");
  }

  state.isDisconnecting = false;
}

async function connect() {
  if (state.isConnected || state.isConnecting) {
    return;
  }

  state.isConnecting = true;
  state.processedCallIds.clear();
  setActivity("idle");
  setUiState("connecting");
  setHint("Requesting microphone access and opening the live session.", "neutral");

  try {
    state.sessionId = generateSessionId();

    await fetchJson(routes.sessionReset, {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId }),
    });

    state.config = await fetchJson(routes.realtimeConfig);
    applyBranding(state.config);

    state.localStream = await navigator.mediaDevices.getUserMedia({
      audio: state.config.mic_audio_constraints || {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: { ideal: 48000 },
        sampleSize: { ideal: 16 },
      },
    });

    const peerConnection = new RTCPeerConnection();
    const remoteStream = new MediaStream();

    state.pc = peerConnection;
    state.remoteStream = remoteStream;
    refs.remoteAudio.srcObject = remoteStream;

    peerConnection.ontrack = (event) => {
      for (const track of event.streams[0]?.getTracks?.() || []) {
        remoteStream.addTrack(track);
      }
      refs.remoteAudio.play().catch(() => {});
    };

    peerConnection.onconnectionstatechange = () => {
      const connectionState = peerConnection.connectionState || "new";
      logEvent(`Peer connection state: ${connectionState}`);

      if (state.isDisconnecting) {
        return;
      }

      if (connectionState === "failed") {
        void disconnect({
          resetSession: false,
          reason: "error",
          message: "Connection dropped. Start the call again.",
        });
        return;
      }

      if ((connectionState === "closed" || connectionState === "disconnected") && (state.isConnected || state.isConnecting)) {
        void disconnect({
          resetSession: false,
          reason: "ended",
          message: "Call ended. Start again anytime.",
        });
      }
    };

    const dataChannel = peerConnection.createDataChannel("oai-events");
    state.dataChannel = dataChannel;

    dataChannel.onopen = () => {
      state.isConnecting = false;
      state.isConnected = true;
      setUiState("live");
      setActivity("live");
      setHint("Voice session is live.", "live");

      if (state.config.ai_speaks_first) {
        sendRealtimeEvent({
          type: "response.create",
          response: {
            output_modalities: ["audio"],
            input: [],
            instructions: state.config.initial_greeting,
          },
        });
      }
    };

    dataChannel.onmessage = async (message) => {
      const event = parseJsonSafe(message.data, null);
      if (!event) {
        return;
      }

      try {
        await handleRealtimeEvent(event);
      } catch (error) {
        logEvent(`Realtime event handling failed: ${trimText(error.message || String(error), 120)}`);
      }
    };

    dataChannel.onclose = () => {
      if (!state.isDisconnecting && (state.isConnected || state.isConnecting)) {
        void disconnect({
          resetSession: false,
          reason: "ended",
          message: "Call ended. Start again anytime.",
        });
      }
    };

    for (const track of state.localStream.getTracks()) {
      peerConnection.addTrack(track, state.localStream);
    }

    const offer = await peerConnection.createOffer({ offerToReceiveAudio: true });
    await peerConnection.setLocalDescription(offer);

    const answerSdp = await createRealtimeCall(offer.sdp);
    await peerConnection.setRemoteDescription({
      type: "answer",
      sdp: answerSdp,
    });
  } catch (error) {
    console.error(error);
    state.isConnecting = false;
    await disconnect({
      resetSession: false,
      reason: "error",
      message: trimText(error.message || String(error), 140),
    });
  }
}

async function handlePrimaryAction() {
  if (state.isConnecting || state.isDisconnecting) {
    return;
  }

  if (state.isConnected) {
    await disconnect({
      resetSession: true,
      reason: "ended",
      message: "Call ended. Start again anytime.",
    });
    return;
  }

  await connect();
}

async function bootstrap() {
  setUiState("idle");
  setActivity("idle");
  setHint("Allow microphone access when prompted.");

  try {
    state.health = await fetchJson(routes.health);
    applyBranding(state.health);
  } catch (error) {
    logEvent(`Health check failed: ${trimText(error.message || String(error), 120)}`);
  }
}

refs.connectButton.addEventListener("click", handlePrimaryAction);

window.addEventListener("pagehide", () => {
  stopTracks(state.localStream);
  stopTracks(state.remoteStream);
  try {
    state.dataChannel?.close();
  } catch {}
  try {
    state.pc?.close();
  } catch {}
});

bootstrap();
