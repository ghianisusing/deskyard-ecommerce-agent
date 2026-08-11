const toggleBtn = document.getElementById("chat-toggle");
const closeBtn  = document.getElementById("chat-close");
const panel     = document.getElementById("chat-panel");
const messagesEl = document.getElementById("messages");
const formEl    = document.getElementById("chat-form");
const inputEl   = document.getElementById("chat-input");

let history  = []; // [{role: "user"|"assistant", content: "…"}]
let greeted  = false;
let isSending = false;

function addMessage(text, cssClass) {
  const div = document.createElement("div");
  div.className = `msg ${cssClass}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function addTypingIndicator() {
  const div = document.createElement("div");
  div.className = "msg agent";
  div.id = "typing-indicator";
  div.textContent = "…";
  div.style.opacity = "0.5";
  div.style.fontStyle = "italic";
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function openChat() {
  panel.classList.remove("hidden");
  toggleBtn.setAttribute("aria-expanded", "true");
  if (!greeted) {
    setTimeout(() => addMessage("Hi! How can I help you today?", "agent"), 200);
    greeted = true;
  }
  setTimeout(() => inputEl.focus(), 300);
}

function closeChat() {
  panel.classList.add("hidden");
  toggleBtn.setAttribute("aria-expanded", "false");
}

toggleBtn.addEventListener("click", () => {
  panel.classList.contains("hidden") ? openChat() : closeChat();
});

closeBtn.addEventListener("click", closeChat);

// Close on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !panel.classList.contains("hidden")) closeChat();
});

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || isSending) return;

  isSending = true;
  const sendBtn = formEl.querySelector("button[type=submit]");
  sendBtn.disabled = true;

  addMessage(text, "user");
  inputEl.value = "";

  const typingEl = addTypingIndicator();

  try {
    const res = await fetch("/api/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history }),
    });

    typingEl.remove();

    let data;
    try {
      data = await res.json();
    } catch {
      addMessage(`Server error (status ${res.status}). Check the terminal running runserver.`, "system");
      return;
    }

    if (data.error) {
      addMessage(data.error, "system");
      return;
    }

    addMessage(data.reply, "agent");
    history.push({ role: "user", content: text });
    history.push({ role: "assistant", content: data.reply });

    if (data.escalate) {
      addMessage("🔔 This conversation has been flagged for a human agent to follow up.", "system");
    }
  } catch (err) {
    typingEl.remove();
    addMessage(`Couldn't reach the server: ${err.message}`, "system");
  } finally {
    isSending = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
});
