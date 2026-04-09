const state = {
  config: null,
  health: null,
  pc: null,
  dataChannel: null,
  localStream: null,
  remoteStream: null,
  sessionId: null,
  isConnected: false,
  isMuted: false,
  processedCallIds: new Set(),
  transcriptNodes: new Map(),
  assistantDrafts: new Map(),
};

const refs = {
  connectButton: document.getElementById("connectButton"),
  disconnectButton: document.getElementById("disconnectButton"),
  muteButton: document.getElementById("muteButton"),
  connectionLabel: document.getElementById("connectionLabel"),
  connectionDetail: document.getElementById("connectionDetail"),
  sessionLabel: document.getElementById("sessionLabel"),
  sessionDetail: document.getElementById("sessionDetail"),
  stageTitle: document.getElementById("stageTitle"),
  stageText: document.getElementById("stageText"),
  assistantChip: document.getElementById("assistantChip"),
  modelChip: document.getElementById("modelChip"),
  voiceChip: document.getElementById("voiceChip"),
  knowledgeChip: document.getElementById("knowledgeChip"),
  routeChip: document.getElementById("routeChip"),
  searchChip: document.getElementById("searchChip"),
  sessionIdValue: document.getElementById("sessionIdValue"),
  publicUrlValue: document.getElementById("publicUrlValue"),
  securityNote: document.getElementById("securityNote"),
  memorySummary: document.getElementById("memorySummary"),
  knowledgeSummary: document.getElementById("knowledgeSummary"),
  hintSummary: document.getElementById("hintSummary"),
  eventLog: document.getElementById("eventLog"),
  callerFeed: document.getElementById("callerFeed"),
  assistantFeed: document.getElementById("assistantFeed"),
  eventBadge: document.getElementById("eventBadge"),
  orbUser: document.getElementById("orbUser"),
  orbAgent: document.getElementById("orbAgent"),
  remoteAudio: document.getElementById("remoteAudio"),
};

function generateSessionId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function setConnection(label, detail) {
  refs.connectionLabel.textContent = label;
  refs.connectionDetail.textContent = detail;
}

function setSession(label, detail) {
  refs.sessionLabel.textContent = label;
  refs.sessionDetail.textContent = detail;
}

function setStage(title, text) {
  refs.stageTitle.textContent = title;
  refs.stageText.textContent = text;
}

function setBadge(text, kind = "neutral") {
  refs.eventBadge.textContent = text;
  refs.eventBadge.className = `badge ${kind}`;
}

function activateOrb(target, active) {
  refs[target].classList.toggle("active", active);
}

function appendEvent(text) {
  const item = document.createElement("li");
  item.textContent = text;
  refs.eventLog.prepend(item);
  while (refs.eventLog.children.length > 8) {
    refs.eventLog.removeChild(refs.eventLog.lastElementChild);
  }
}

function ensureFeedReady(feed) {
  if (!feed.classList.contains("empty-state")) {
    return;
  }
  feed.innerHTML = "";
  feed.classList.remove("empty-state");
}

function resetFeed(feed, message) {
  feed.innerHTML = `<p>${message}</p>`;
  feed.classList.add("empty-state");
}

function entryKey(role, itemId) {
  return `${role}:${itemId}`;
}

function createTranscriptEntry(role, itemId, initialText, isLive = false) {
  const feed = role === "caller" ? refs.callerFeed : refs.assistantFeed;
  ensureFeedReady(feed);
  const wrapper = document.createElement("article");
  wrapper.className = `transcript-entry${isLive ? " live" : ""}`;
  wrapper.dataset.entryKey = entryKey(role, itemId);

  const meta = document.createElement("div");
  meta.className = "transcript-meta";

  const speaker = document.createElement("span");
  speaker.textContent = role === "caller" ? "Caller" : "Assistant";
  const time = document.createElement("span");
  time.textContent = nowLabel();

  const body = document.createElement("p");
  body.textContent = initialText;

  meta.append(speaker, time);
  wrapper.append(meta, body);
  feed.append(wrapper);
  feed.scrollTop = feed.scrollHeight;
  state.transcriptNodes.set(entryKey(role, itemId), wrapper);
  return wrapper;
}

function upsertTranscript(role, itemId, text, isLive = false) {
  if (!text || !text.trim()) {
    return;
  }
  const key = entryKey(role, itemId);
  let entry = state.transcriptNodes.get(key);
  if (!entry) {
    entry = createTranscriptEntry(role, itemId, text, isLive);
  } else {
    entry.classList.toggle("live", isLive);
    const body = entry.querySelector("p");
    body.textContent = text;
    const stamp = entry.querySelector(".transcript-meta span:last-child");
    if (stamp) {
      stamp.textContent = nowLabel();
    }
  }
  const feed = role === "caller" ? refs.callerFeed : refs.assistantFeed;
  feed.scrollTop = feed.scrollHeight;
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

function sendRealtimeEvent(event) {
  if (!state.dataChannel || state.dataChannel.readyState !== "open") {
    return;
  }
  state.dataChannel.send(JSON.stringify(event));
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

function getFunctionCallsFromResponse(event) {
  const output = event?.response?.output;
  if (!Array.isArray(output)) {
    return [];
  }
  return output.filter((item) => item?.type === "function_call" && item?.call_id && item?.name);
}

async function syncTranscriptContext(transcript) {
  const data = await fetchJson("/socket/socket/api/context/transcript", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.sessionId,
      transcript,
    }),
  });

  refs.routeChip.textContent = data?.context?.routed_issue_label || "General";
  refs.searchChip.textContent = data?.search_recommended ? "Search likely" : "Not needed";
  refs.memorySummary.textContent = data?.summary || refs.memorySummary.textContent;
  refs.hintSummary.textContent = data?.system_hint || "No new routing hint right now.";

  if (data?.context?.routed_issue_label) {
    appendEvent(`Routed as ${data.context.routed_issue_label}.`);
  }

  return data;
}

async function invokeTool(name, args) {
  if (!state.sessionId) {
    return { ok: false, error: "Session is not initialized." };
  }

  if (name === "remember_call_context") {
    const result = await fetchJson("/socket/api/tool/remember-context", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        payload: args || {},
      }),
    });
    refs.memorySummary.textContent = result.summary || "Context remembered.";
    appendEvent("Call context updated.");
    return result;
  }

  if (name === "get_call_context") {
    const result = await fetchJson("/socket/api/tool/get-context", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
      }),
    });
    refs.memorySummary.textContent = result.summary || "Context loaded.";
    appendEvent("Call context fetched.");
    return result;
  }

  if (name === "search_qualys_support_knowledge") {
    setBadge("Checking SearchUnify", "search");
    const result = await fetchJson("/socket/api/tool/search", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        query: String(args?.query || ""),
        product_area: args?.product_area || "",
      }),
    });

    const best = result?.best_result || {};
    const title = trimText(best.title || "No strong title");
    const snippet = trimText(best.snippet || result?.note || result?.error || "No grounded snippet returned.", 220);
    refs.knowledgeSummary.textContent = `${title}. ${snippet}`;
    refs.searchChip.textContent = result?.response_mode || "Grounded";
    appendEvent(
      result?.best_result
        ? `Knowledge match: ${trimText(best.title || "Support result", 72)}`
        : `Knowledge lookup returned ${result?.results?.length || 0} results.`
    );
    return result;
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
    appendEvent(`Tool call: ${call.name}`);

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

function handleAssistantTranscriptDelta(event, final = false) {
  const itemId = event.item_id || `assistant-${event.response_id || "live"}`;
  const chunk = event.delta || event.transcript || event.text || "";
  const previous = state.assistantDrafts.get(itemId) || "";
  const next = final ? (event.transcript || event.text || previous).trim() : `${previous}${chunk}`;
  state.assistantDrafts.set(itemId, next);
  upsertTranscript("assistant", itemId, next, !final);
  if (final) {
    state.assistantDrafts.delete(itemId);
  }
}

async function handleRealtimeEvent(event) {
  if (!event?.type) {
    return;
  }

  switch (event.type) {
    case "session.created":
      setSession("Ready", "Realtime session created");
      appendEvent("Realtime session created.");
      break;
    case "session.updated":
      appendEvent("Session configuration updated.");
      break;
    case "input_audio_buffer.speech_started":
      activateOrb("orbUser", true);
      setBadge("Caller speaking", "live");
      break;
    case "input_audio_buffer.speech_stopped":
      activateOrb("orbUser", false);
      setBadge("Caller finished", "neutral");
      break;
    case "response.created":
      activateOrb("orbAgent", true);
      setConnection("Connected", "Assistant is responding");
      setBadge("Assistant responding", "live");
      break;
    case "response.done":
      activateOrb("orbAgent", false);
      setConnection("Connected", "Assistant waiting for caller");
      setBadge("Listening", "neutral");
      await handleFunctionCalls(event);
      break;
    case "conversation.item.input_audio_transcription.completed": {
      const transcript = String(event.transcript || "").trim();
      if (!transcript) {
        break;
      }
      upsertTranscript("caller", event.item_id || `caller-${Date.now()}`, transcript, false);
      await syncTranscriptContext(transcript);
      break;
    }
    case "response.output_audio_transcript.delta":
    case "response.output_text.delta":
      handleAssistantTranscriptDelta(event, false);
      break;
    case "response.output_audio_transcript.done":
    case "response.output_text.done":
      handleAssistantTranscriptDelta(event, true);
      break;
    case "error": {
      const message = event.error?.message || "Unknown Realtime error";
      appendEvent(`Realtime error: ${trimText(message, 120)}`);
      setConnection("Error", message);
      setBadge("Error", "search");
      break;
    }
    default:
      break;
  }
}

async function createRealtimeCall(config, offerSdp) {
  const session = JSON.parse(JSON.stringify(config.session || {}));
  session.model = session.model || config.model;
  const form = new FormData();
  form.set("sdp", offerSdp);
  form.set("session", JSON.stringify(session));

  const response = await fetch(`${config.openai_api_base}/realtime/calls`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.openai_api_key}`,
    },
    body: form,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `OpenAI create call failed with ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json();
    const sdp = payload?.sdp || payload?.answer?.sdp || payload?.answer || "";
    if (!sdp) {
      throw new Error("OpenAI did not return an SDP answer.");
    }
    return sdp;
  }
  const sdp = await response.text();
  if (!sdp) {
    throw new Error("OpenAI returned an empty SDP answer.");
  }
  return sdp;
}

async function connect() {
  if (state.isConnected) {
    return;
  }

  refs.connectButton.disabled = true;
  setConnection("Starting", "Fetching config and asking for microphone access");
  setSession("Preparing", "Creating browser voice session");
  setStage("Opening a direct Realtime link", "The browser is preparing a WebRTC offer and the tool bridge.");
  appendEvent("Starting browser WebRTC session.");

  try {
    state.transcriptNodes.clear();
    state.assistantDrafts.clear();
    refs.eventLog.innerHTML = "";
    resetFeed(refs.callerFeed, "The caller transcript will appear here.");
    resetFeed(refs.assistantFeed, "The assistant transcript will appear here.");
    refs.memorySummary.textContent = "No remembered context yet.";
    refs.knowledgeSummary.textContent = "No knowledge lookup has run yet.";
    refs.hintSummary.textContent = "Route and frustration hints will show up here when the backend sees something important.";

    state.sessionId = generateSessionId();
    refs.sessionIdValue.textContent = state.sessionId;
    await fetchJson("/socket/api/session/reset", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId }),
    });

    state.config = await fetchJson("/socket/api/realtime-config");
    refs.assistantChip.textContent = state.config.assistant_name || "Aira";
    refs.modelChip.textContent = state.config.model || "gpt-realtime";
    refs.voiceChip.textContent = state.config.voice || "unknown";
    refs.knowledgeChip.textContent = state.config.knowledge_backend_enabled
      ? state.config.knowledge_backend_name || "Enabled"
      : "Disabled";
    refs.publicUrlValue.textContent = state.config.public_url || window.location.origin;
    refs.securityNote.textContent = state.config.developer_note || refs.securityNote.textContent;

    state.localStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });

    state.pc = new RTCPeerConnection();
    state.remoteStream = new MediaStream();
    refs.remoteAudio.srcObject = state.remoteStream;

    state.pc.ontrack = (event) => {
      for (const track of event.streams[0]?.getTracks?.() || []) {
        state.remoteStream.addTrack(track);
      }
      refs.remoteAudio.play().catch(() => {});
    };

    state.pc.onconnectionstatechange = () => {
      const connectionState = state.pc?.connectionState || "new";
      setSession(connectionState === "connected" ? "Live" : "Connecting", `Peer connection: ${connectionState}`);
      appendEvent(`Peer connection is ${connectionState}.`);
    };

    state.dataChannel = state.pc.createDataChannel("oai-events");
    state.dataChannel.onopen = () => {
      state.isConnected = true;
      refs.connectButton.disabled = true;
      refs.disconnectButton.disabled = false;
      refs.muteButton.disabled = false;
      setConnection("Connected", "Microphone live and Realtime channel open");
      setStage("Live support session running", "Speak normally. The assistant will answer over the remote audio stream.");
      setBadge("Listening", "neutral");
      appendEvent("Data channel opened.");

      sendRealtimeEvent({
        type: "session.update",
        session: state.config.session,
      });

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

    state.dataChannel.onmessage = async (message) => {
      const event = parseJsonSafe(message.data, null);
      if (!event) {
        return;
      }
      await handleRealtimeEvent(event);
    };

    state.dataChannel.onclose = () => {
      appendEvent("Data channel closed.");
    };

    for (const track of state.localStream.getTracks()) {
      state.pc.addTrack(track, state.localStream);
    }

    const offer = await state.pc.createOffer({ offerToReceiveAudio: true });
    await state.pc.setLocalDescription(offer);
    const answerSdp = await createRealtimeCall(state.config, offer.sdp);
    await state.pc.setRemoteDescription({
      type: "answer",
      sdp: answerSdp,
    });
  } catch (error) {
    console.error(error);
    appendEvent(`Failed to connect: ${trimText(error.message || String(error), 120)}`);
    setConnection("Error", error.message || "Failed to connect");
    setStage("Connection failed", "Check browser mic permissions and the OpenAI configuration, then try again.");
    refs.connectButton.disabled = false;
    refs.disconnectButton.disabled = true;
    refs.muteButton.disabled = true;
    await disconnect(false);
  }
}

async function disconnect(resetSession = true) {
  try {
    if (resetSession && state.sessionId) {
      await fetchJson("/socket/api/session/reset", {
        method: "POST",
        body: JSON.stringify({ session_id: state.sessionId }),
      });
    }
  } catch (error) {
    console.warn("Session reset failed", error);
  }

  if (state.dataChannel) {
    state.dataChannel.close();
  }
  if (state.pc) {
    state.pc.close();
  }
  if (state.localStream) {
    for (const track of state.localStream.getTracks()) {
      track.stop();
    }
  }
  if (state.remoteStream) {
    for (const track of state.remoteStream.getTracks()) {
      track.stop();
    }
  }

  state.pc = null;
  state.dataChannel = null;
  state.localStream = null;
  state.remoteStream = null;
  state.isConnected = false;
  state.isMuted = false;
  state.processedCallIds.clear();
  state.transcriptNodes.clear();
  state.assistantDrafts.clear();
  state.sessionId = null;
  refs.remoteAudio.srcObject = null;
  refs.disconnectButton.disabled = true;
  refs.muteButton.disabled = true;
  refs.connectButton.disabled = false;
  refs.muteButton.textContent = "Mute Mic";
  refs.sessionIdValue.textContent = "Not started";
  resetFeed(refs.callerFeed, "The caller transcript will appear here.");
  resetFeed(refs.assistantFeed, "The assistant transcript will appear here.");
  refs.memorySummary.textContent = "No remembered context yet.";
  refs.knowledgeSummary.textContent = "No knowledge lookup has run yet.";
  refs.hintSummary.textContent = "Route and frustration hints will show up here when the backend sees something important.";
  refs.routeChip.textContent = "General";
  refs.searchChip.textContent = "Not needed";
  setConnection("Disconnected", "Microphone and Realtime channel closed");
  setSession("Idle", "No active browser session");
  setStage("Ready for a desktop browser call", "Grant microphone access, then the browser connects straight to OpenAI Realtime over WebRTC.");
  setBadge("Waiting for audio", "neutral");
  activateOrb("orbUser", false);
  activateOrb("orbAgent", false);
  appendEvent("Voice session disconnected.");
}

function toggleMute() {
  if (!state.localStream) {
    return;
  }
  state.isMuted = !state.isMuted;
  for (const track of state.localStream.getAudioTracks()) {
    track.enabled = !state.isMuted;
  }
  refs.muteButton.textContent = state.isMuted ? "Unmute Mic" : "Mute Mic";
  appendEvent(state.isMuted ? "Microphone muted." : "Microphone unmuted.");
}

async function bootstrap() {
  try {
    state.health = await fetchJson("/socket/health");
    refs.assistantChip.textContent = state.health.assistant_name || refs.assistantChip.textContent;
    refs.modelChip.textContent = state.health.model || refs.modelChip.textContent;
    refs.voiceChip.textContent = state.health.voice || refs.voiceChip.textContent;
    refs.knowledgeChip.textContent = state.health.knowledge_backend_enabled
      ? state.health.knowledge_backend_name || "Enabled"
      : "Disabled";
    refs.publicUrlValue.textContent = state.health.public_url || window.location.origin;
  } catch (error) {
    appendEvent(`Health check failed: ${trimText(error.message || String(error), 120)}`);
  }
}

refs.connectButton.addEventListener("click", connect);
refs.disconnectButton.addEventListener("click", () => disconnect(true));
refs.muteButton.addEventListener("click", toggleMute);

bootstrap();
