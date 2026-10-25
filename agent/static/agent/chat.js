const toggleBtn = document.getElementById("chat-toggle");
const closeBtn  = document.getElementById("chat-close");
const panel     = document.getElementById("chat-panel");
const messagesEl = document.getElementById("messages");
const formEl    = document.getElementById("chat-form");
const inputEl   = document.getElementById("chat-input");
const deskieEls = document.querySelectorAll(".deskie");
const voiceToggleBtn = document.getElementById("voice-toggle");
const voiceStatus     = document.getElementById("voice-status");
const voiceStatusText = document.getElementById("voice-status-text");
const floatingEl           = document.getElementById("deskie-floating");
const floatingStatusText   = document.getElementById("deskie-floating-status");
const floatingEndBtn       = document.getElementById("deskie-floating-end");
const floatingTranscriptBtn = document.getElementById("deskie-floating-transcript");

// The server keeps the conversation history in the session. This flag
// tells it to start fresh on the first message after a page load, so the
// agent never remembers a conversation the customer can't see anymore.
let newConversation = true;
let greeted  = false;
let isSending = false;
let deskieResetTimer = null;

// Voice call mode (Web Speech API) — talk to Deskie hands-free instead of
// typing. Not supported everywhere: solid in Chrome/Edge, weak-to-absent
// in Firefox/Safari. The button is disabled outright when unsupported
// rather than left to fail silently on click.
const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const voiceSupported = !!SpeechRecognitionCtor && "speechSynthesis" in window;
let voiceActive = false;
let recognizer = null;

if (voiceToggleBtn && !voiceSupported) {
  voiceToggleBtn.disabled = true;
  voiceToggleBtn.title = "Voice chat isn't supported in this browser — try Chrome or Edge.";
}

// Deskie (both copies — toggle button + chat header) always mirrors the
// same state. "idle" and "listening" loop indefinitely via CSS; "happy"
// and "concerned" are one-shot poses that this function automatically
// eases back to idle after `holdMs`, so callers don't need to remember to
// reset it themselves.
function setDeskieState(state, holdMs = 0) {
  clearTimeout(deskieResetTimer);
  deskieEls.forEach((el) => { el.dataset.state = state; });
  if (holdMs > 0) {
    deskieResetTimer = setTimeout(() => {
      deskieEls.forEach((el) => { el.dataset.state = "idle"; });
    }, holdMs);
  }
}

// Clones one of the existing Deskie SVGs (the header copy) rather than
// duplicating its markup here — agent/templates/agent/face.html stays the
// single source of truth for what Deskie looks like. Frozen at whatever
// state it's given; per-message avatars are a snapshot of Deskie's mood
// at that moment, not a live-updating one.
function makeDeskieAvatar(state) {
  const template = deskieEls[0];
  if (!template) return null;
  const clone = template.cloneNode(true);
  clone.removeAttribute("id");
  clone.classList.remove("deskie--xs", "deskie--sm");
  clone.classList.add("deskie--msg");
  clone.dataset.state = state;
  return clone;
}

function addMessage(text, cssClass, deskieState = null) {
  const bubble = document.createElement("div");
  bubble.className = `msg ${cssClass}`;
  bubble.textContent = text;

  if (cssClass === "agent" && deskieState) {
    const row = document.createElement("div");
    row.className = "msg-row agent-row";
    const avatar = makeDeskieAvatar(deskieState);
    if (avatar) row.appendChild(avatar);
    row.appendChild(bubble);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return bubble;
  }

  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function addTypingIndicator() {
  const bubble = document.createElement("div");
  bubble.className = "msg agent";
  bubble.textContent = "…";
  bubble.style.opacity = "0.5";
  bubble.style.fontStyle = "italic";

  const row = document.createElement("div");
  row.className = "msg-row agent-row";
  row.id = "typing-indicator";
  const avatar = makeDeskieAvatar("thinking");
  if (avatar) row.appendChild(avatar);
  row.appendChild(bubble);

  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return row; // .remove() on this takes the avatar with it
}

function openChat() {
  panel.classList.remove("hidden");
  toggleBtn.setAttribute("aria-expanded", "true");
  if (!greeted) {
    setTimeout(() => addMessage("Hi! How can I help you today?", "agent", "idle"), 200);
    greeted = true;
  }
  setTimeout(() => inputEl.focus(), 300);
}

function closeChat() {
  panel.classList.add("hidden");
  toggleBtn.setAttribute("aria-expanded", "false");
  // Closing the panel no longer ends an active call — the floating
  // assistant is the call's real UI now, this just hides the transcript
  // peek. Only reset Deskie's expression if no call is managing it.
  if (!voiceActive) setDeskieState("idle");
}

toggleBtn.addEventListener("click", () => {
  panel.classList.contains("hidden") ? openChat() : closeChat();
});

closeBtn.addEventListener("click", closeChat);

inputEl.addEventListener("focus", () => {
  if (!isSending && !voiceActive) setDeskieState("listening");
});
inputEl.addEventListener("blur", () => {
  if (!isSending && !voiceActive) setDeskieState("idle");
});

// Close on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !panel.classList.contains("hidden")) closeChat();
});

// Keeps the in-panel status bar and the floating assistant's status text
// in sync — the panel one only becomes visible again if the user peeks at
// the transcript mid-call via "View chat", but both should always agree.
function setVoiceStatus(text) {
  if (voiceStatusText) voiceStatusText.textContent = text;
  if (floatingStatusText) floatingStatusText.textContent = text;
}

// Shared by both the typed-message form and voice call mode, so the
// request/response/error handling only lives in one place. speakReply
// controls whether the response is read aloud (voice mode) and whether
// the mic starts listening again afterward (hands-free loop).
async function sendToAgent(text, { speakReply = false } = {}) {
  isSending = true;
  const sendBtn = formEl.querySelector("button[type=submit]");
  sendBtn.disabled = true;

  addMessage(text, "user");

  const typingEl = addTypingIndicator();
  setDeskieState("thinking");
  if (voiceActive) setVoiceStatus("💭 Deskie is thinking…");

  const finishVoiceTurn = () => {
    if (voiceActive) listenOnce();
  };

  try {
    const res = await fetch("/api/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, new_conversation: newConversation }),
    });

    typingEl.remove();

    let data;
    try {
      data = await res.json();
    } catch {
      const msg = `Server error (status ${res.status}). Check the terminal running runserver.`;
      addMessage(msg, "system");
      setDeskieState("concerned", 2000);
      if (speakReply) speak(msg, finishVoiceTurn);
      return;
    }

    if (data.error) {
      addMessage(data.error, "system");
      setDeskieState("concerned", 2000);
      if (speakReply) speak(data.error, finishVoiceTurn);
      return;
    }

    addMessage(data.reply, "agent", "happy");
    newConversation = false;

    const afterReply = () => {
      if (data.escalate) {
        addMessage("🔔 This conversation has been flagged for a human agent to follow up.", "system");
        setDeskieState("concerned", 2000);
      } else if (!speakReply) {
        setDeskieState("happy", 1200);
      }
      finishVoiceTurn();
    };

    if (speakReply) {
      speak(data.reply, afterReply);
    } else {
      afterReply();
    }
  } catch (err) {
    typingEl.remove();
    const msg = `Couldn't reach the server: ${err.message}`;
    addMessage(msg, "system");
    setDeskieState("concerned", 2000);
    if (speakReply) speak(msg, finishVoiceTurn);
  } finally {
    isSending = false;
    sendBtn.disabled = false;
    if (!voiceActive) inputEl.focus();
  }
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || isSending) return;
  inputEl.value = "";

  // Typing while a voice call is listening would otherwise race with
  // whatever the mic picks up next — fully disable the old recognizer's
  // handlers before aborting it, so its onend can't restart listening
  // out from under the message we're about to send.
  if (voiceActive && recognizer) {
    const rec = recognizer;
    rec.onresult = null;
    rec.onerror = null;
    rec.onend = null;
    try { rec.abort(); } catch { /* already stopped */ }
  }

  await sendToAgent(text, { speakReply: false });
});

// --- Voice call mode ------------------------------------------------

let audioCtx = null; // reused across turns within a call; one per page load

// Speaks `text` using OpenAI's TTS API (a real neural voice, not the
// browser's built-in one) and drives the floating Deskie's mouth from
// the actual audio waveform as it plays, via the Web Audio API's
// AnalyserNode — genuine lip-sync-style timing, not a fixed loop.
//
// Two layers of fallback, so a voice call can never go silent:
//   1. If Web Audio setup fails, the OpenAI audio still plays normally,
//      just with the CSS keyframe mouth loop instead of live sync.
//   2. If the /api/tts/ request itself fails (quota, network, missing
//      key), falls all the way back to the browser's own SpeechSynthesis.
async function speak(text, onDone) {
  setDeskieState("speaking");
  setVoiceStatus("🔊 Deskie is speaking…");

  let blob;
  try {
    const res = await fetch("/api/tts/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`TTS request failed (${res.status})`);
    blob = await res.blob();
  } catch {
    speakWithBrowserVoice(text, onDone);
    return;
  }

  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  const mouthEl = floatingEl ? floatingEl.querySelector(".mouth-speaking") : null;
  let rafId = null;
  let source = null;
  let analyser = null;

  const cleanup = () => {
    cancelAnimationFrame(rafId);
    if (source) { try { source.disconnect(); } catch { /* already gone */ } }
    if (analyser) { try { analyser.disconnect(); } catch { /* already gone */ } }
    URL.revokeObjectURL(url);
    if (mouthEl) {
      mouthEl.style.animation = "";  // hand control back to the CSS loop
      mouthEl.style.transform = "";
    }
    setDeskieState("idle");
    if (onDone) onDone();
  };
  audio.onended = cleanup;
  audio.onerror = cleanup;

  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") await audioCtx.resume();

    source = audioCtx.createMediaElementSource(audio);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioCtx.destination); // must connect to destination or audio is silent

    const data = new Uint8Array(analyser.frequencyBinCount);
    if (mouthEl) mouthEl.style.animation = "none"; // JS drives the mouth now, not the CSS keyframe

    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sumSquares += v * v;
      }
      const rms = Math.sqrt(sumSquares / data.length); // ~0 (silence) to ~1 (loud)
      if (mouthEl) {
        const scale = Math.min(1, 0.3 + rms * 3.5).toFixed(2);
        mouthEl.style.transform = `scaleY(${scale})`;
      }
      if (!audio.paused && !audio.ended) rafId = requestAnimationFrame(tick);
    };
    audio.addEventListener("play", tick);
  } catch {
    // Web Audio setup didn't work out — audio still plays below, mouth
    // just falls back to the default CSS "speaking" loop instead.
  }

  try {
    await audio.play();
  } catch {
    cleanup();
  }
}

// Last-resort fallback if OpenAI TTS is unavailable for any reason.
function speakWithBrowserVoice(text, onDone) {
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  setDeskieState("speaking");
  setVoiceStatus("🔊 Deskie is speaking…");
  const done = () => {
    setDeskieState("idle");
    if (onDone) onDone();
  };
  utterance.onend = done;
  utterance.onerror = done;
  window.speechSynthesis.speak(utterance);
}

function listenOnce() {
  if (!voiceActive) return;

  const rec = new SpeechRecognitionCtor();
  recognizer = rec;
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  // Tracks whether onresult (or a fatal permission error) already decided
  // what happens next, so onend doesn't ALSO restart listening for the
  // same turn — onend fires after both success and most error cases.
  let handled = false;

  setVoiceStatus("🎙️ Listening…");
  setDeskieState("listening");

  rec.onresult = (e) => {
    handled = true;
    if (isSending) return; // a turn is already in flight, ignore this one
    const transcript = e.results[0][0].transcript.trim();
    if (transcript && voiceActive) {
      sendToAgent(transcript, { speakReply: true });
    } else if (voiceActive) {
      listenOnce();
    }
  };

  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      handled = true;
      addMessage("Microphone access is blocked — allow microphone permissions to use voice chat.", "system");
      endVoiceMode();
    }
    // Other errors (no-speech, aborted, network, audio-capture) are left
    // for onend to retry, so a moment of silence doesn't end the call.
  };

  rec.onend = () => {
    if (!handled && voiceActive) listenOnce();
  };

  try {
    rec.start();
  } catch {
    setVoiceStatus("Couldn't start the microphone.");
  }
}

function startVoiceMode() {
  if (!voiceSupported || voiceActive) return;
  if (panel.classList.contains("hidden")) openChat();

  voiceActive = true;

  // Deskie moves out of the chat panel and into the floating assistant —
  // the panel and its small toggle button step aside for the call.
  panel.classList.add("hidden");
  toggleBtn.classList.add("hidden");
  floatingEl.classList.remove("hidden");
  voiceStatus.classList.remove("hidden"); // populated in case the panel gets peeked at

  voiceToggleBtn.setAttribute("aria-pressed", "true");
  voiceToggleBtn.textContent = "📞 End Call";
  setVoiceStatus("🎙️ Listening…");
  addMessage("🎙️ Voice call started — say something to Deskie.", "system");
  listenOnce();
}

function endVoiceMode() {
  if (!voiceActive) return;
  voiceActive = false;

  if (recognizer) {
    try { recognizer.abort(); } catch { /* already stopped */ }
  }
  window.speechSynthesis.cancel();
  if (audioCtx && audioCtx.state === "running") {
    audioCtx.suspend().catch(() => {});
  }

  floatingEl.classList.add("hidden");
  toggleBtn.classList.remove("hidden");
  panel.classList.add("hidden");
  voiceStatus.classList.add("hidden");
  voiceToggleBtn.setAttribute("aria-pressed", "false");
  voiceToggleBtn.textContent = "📞 Call";
  setDeskieState("idle");
}

if (voiceToggleBtn && voiceSupported) {
  voiceToggleBtn.addEventListener("click", () => {
    voiceActive ? endVoiceMode() : startVoiceMode();
  });
}

if (floatingEndBtn) {
  floatingEndBtn.addEventListener("click", endVoiceMode);
}

// Lets the user peek at the text transcript mid-call without hanging up
// — the floating assistant stays visible and the call keeps running.
// Both the panel and the floating assistant default to the same
// bottom-right corner, so the first time this is used (before the user
// has manually dragged Deskie anywhere), move her out of the way rather
// than letting her sit on top of the panel.
if (floatingTranscriptBtn) {
  floatingTranscriptBtn.addEventListener("click", () => {
    if (!deskieDragged && floatingEl) {
      floatingEl.style.right = "auto";
      floatingEl.style.bottom = "auto";
      floatingEl.style.left = "24px";
      floatingEl.style.top = "24px";
    }
    panel.classList.remove("hidden");
  });
}

// --- Dragging the floating assistant -----------------------------------
// Plain Pointer Events (covers mouse, touch, and pen with one code path).
// Clicking/tapping the card's own buttons should never start a drag.
let deskieDragged = false;

function makeDraggable(el) {
  if (!el) return;

  let dragging = false;
  let startX = 0, startY = 0, startLeft = 0, startTop = 0, elWidth = 0, elHeight = 0;

  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return; // let End Call / View chat work normally
    dragging = true;
    deskieDragged = true; // once moved, respect wherever the user leaves it
    el.classList.add("dragging");
    el.setPointerCapture(e.pointerId);

    const rect = el.getBoundingClientRect();
    startX = e.clientX;
    startY = e.clientY;
    startLeft = rect.left;
    startTop = rect.top;
    elWidth = rect.width;
    elHeight = rect.height;

    // Switch from bottom/right-anchored to left/top-anchored so it can
    // be freely repositioned from here on.
    el.style.right = "auto";
    el.style.bottom = "auto";
    el.style.left = `${startLeft}px`;
    el.style.top = `${startTop}px`;
  });

  el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const newLeft = startLeft + (e.clientX - startX);
    const newTop = startTop + (e.clientY - startY);

    // Clamp so it can never be dragged fully off-screen.
    const maxLeft = Math.max(8, window.innerWidth - elWidth - 8);
    const maxTop = Math.max(8, window.innerHeight - elHeight - 8);
    el.style.left = `${Math.min(Math.max(8, newLeft), maxLeft)}px`;
    el.style.top = `${Math.min(Math.max(8, newTop), maxTop)}px`;
  });

  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("dragging");
    try { el.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  };
  el.addEventListener("pointerup", endDrag);
  el.addEventListener("pointercancel", endDrag);
}

makeDraggable(floatingEl);
