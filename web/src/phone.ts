/**
 * Browser phone: call Linda (an ElevenLabs voice agent) while Guardian listens in.
 *
 * 1. POST /calls/web/start with the caller number -> route (verified / rejected / screen).
 * 2. Screened calls open an ElevenLabs session where Linda answers. Every time the caller finishes
 *    a sentence, the page posts that exchange to /calls/web/{id}/turn: the scorer (Claude + rules)
 *    reads the whole call so far, the dashboard updates, and the family gets an iMessage heads-up
 *    when it looks like a scam.
 * 3. When the score crosses the scam line, Guardian steps in: Linda says goodbye and the call ends;
 *    the backend saves the evidence and texts the family. /calls/web/{id}/end settles any other call.
 */
import { Conversation } from "@elevenlabs/client";

const API = (import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/$/, "");
const HARD_STOP_S = 90;

// CONTRACTS section 4 demo numbers, plus two unknown callers for screening.
const PRESETS = [
  { label: "Unknown caller", hint: "Linda answers, Guardian listens", number: "+12135550177" },
  { label: "Pharmacy (unknown)", hint: "Linda answers, Guardian listens", number: "+18185550123" },
  { label: "Son (David)", hint: "Verified, rings through", number: "+13105550111" },
  { label: "Flagged scam number", hint: "Score 92, rejected", number: "+12135550142" },
];

type Turn = { action: "continue" | "end"; risk: number; red_flags: string[] };

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const el = {
  dial: $("dial"), live: $("live"), result: $("result"),
  presets: $("presets"), number: $<HTMLInputElement>("number"), call: $<HTMLButtonElement>("call"),
  dialError: $("dial-error"), timer: $("timer"),
  liveNumber: $("live-number"), liveStatus: $("live-status"),
  meter: $("meter-fill"), risk: $("risk"), flags: $("flags"), transcript: $("transcript"),
  hangup: $<HTMLButtonElement>("hangup"),
  resultIcon: $("result-icon"), resultTitle: $("result-title"), resultBody: $("result-body"),
  again: $<HTMLButtonElement>("again"),
};

let conversation: Conversation | null = null;
let callId: string | null = null;
let callNumber = "";
let scamCaught = false;
let lindaSaid: string[] = []; // Linda's lines since the caller last spoke
let timerId: number | undefined;
let ending = false;

function show(screen: "dial" | "live" | "result") {
  el.dial.hidden = screen !== "dial";
  el.live.hidden = screen !== "live";
  el.result.hidden = screen !== "result";
}

function renderPresets() {
  for (const p of PRESETS) {
    const b = document.createElement("button");
    b.className = "preset";
    b.innerHTML = `<b>${p.label}</b><span>${p.hint}</span>`;
    b.onclick = () => {
      el.number.value = p.number;
      document.querySelectorAll(".preset").forEach((x) => x.classList.toggle("on", x === b));
    };
    el.presets.append(b);
  }
  (el.presets.firstElementChild as HTMLButtonElement).click();
}

function startTimer() {
  const t0 = Date.now();
  el.timer.textContent = "0:00";
  timerId = window.setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    el.timer.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (s >= HARD_STOP_S) hangUp(); // recording + analysis hard stop
  }, 250);
}

function setRisk(risk: number) {
  const pct = Math.round(risk * 100);
  el.risk.textContent = `${pct}%`;
  el.meter.style.width = `${pct}%`;
  el.meter.dataset.level = risk >= 0.7 ? "high" : risk >= 0.4 ? "mid" : "low";
}

function setFlags(flags: string[]) {
  el.flags.replaceChildren(...flags.map((f) => {
    const li = document.createElement("li");
    li.textContent = f;
    return li;
  }));
}

function addTurn(who: "linda" | "caller", text: string) {
  const li = document.createElement("li");
  li.className = who === "linda" ? "agent" : "caller";
  li.innerHTML = `<span>${who === "linda" ? "Linda" : "You"}</span>`;
  li.append(document.createTextNode(text));
  el.transcript.append(li);
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

/** Guardian listens: score each exchange as soon as the caller finishes speaking. */
async function listen(callerSaid: string) {
  const id = callId;
  const agentSaid = lindaSaid.join(" ");
  lindaSaid = [];
  if (!id || scamCaught) return;
  try {
    const r = await fetch(`${API}/calls/web/${id}/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_said: agentSaid, caller_said: callerSaid }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const out: Turn = await r.json();
    if (id !== callId) return;
    setRisk(out.risk);
    setFlags(out.red_flags);
    if (out.risk >= 0.4 && out.action !== "end") el.liveStatus.textContent = "Guardian is suspicious · family alerted";
    if (out.action === "end") stepIn();
  } catch (err) {
    console.error("Guardian listen failed", err);
  }
}

/** Scam detected: Linda wraps up and Guardian ends the call. */
function stepIn() {
  if (scamCaught) return;
  scamCaught = true;
  el.liveStatus.textContent = "Scam detected · Guardian is ending the call";
  conversation?.sendContextualUpdate(
    "GUARDIAN ALERT: Guardian has identified this caller as a scammer. Do not share anything. " +
      "Say a short, firm goodbye (for example that you never give out information over the phone " +
      "and your family handles these things), then end the call.",
  );
  window.setTimeout(hangUp, 9000); // backstop if Linda keeps talking
}

async function placeCall() {
  el.dialError.hidden = true;
  el.call.disabled = true;
  try {
    const r = await fetch(`${API}/calls/web/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from_number: el.number.value.trim() }),
    });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    callId = body.call_id;
    callNumber = body.number;

    if (body.route === "verified")
      return finish("passed_verified", "Verified caller", "On Linda's verified list, so her phone rang straight away. Not screened or recorded.");
    if (body.route === "rejected")
      return finish("rejected", "Call rejected", "Known scam number. Linda's phone never rang.");

    await startCall(body.signed_url, body.dynamic_variables);
  } catch (err) {
    el.dialError.textContent = `Couldn't place the call: ${(err as Error).message}`;
    el.dialError.hidden = false;
  } finally {
    el.call.disabled = false;
  }
}

async function startCall(signedUrl: string, dynamicVariables: Record<string, string>) {
  scamCaught = false;
  ending = false;
  lindaSaid = [];
  el.transcript.replaceChildren();
  setFlags([]);
  setRisk(0);
  el.liveNumber.textContent = "Linda";
  el.liveStatus.textContent = "Ringing…";
  show("live");

  conversation = await Conversation.startSession({
    signedUrl,
    dynamicVariables,
    onConnect: () => {
      el.liveStatus.textContent = "Connected · Guardian is listening";
      startTimer();
    },
    onMessage: ({ message, role }) => {
      if (!message.trim()) return;
      if (role === "agent") {
        lindaSaid.push(message);
        addTurn("linda", message);
      } else {
        addTurn("caller", message);
        void listen(message);
      }
    },
    onModeChange: ({ mode }) => {
      // Linda has finished her goodbye after Guardian stepped in: hang up like a phone would.
      if (mode === "listening" && scamCaught) hangUp();
    },
    onDisconnect: () => void wrapUp(),
    onError: (message) => console.error("ElevenLabs:", message),
  });
}

async function hangUp() {
  if (ending) return;
  ending = true;
  try {
    await conversation?.endSession();
  } finally {
    await wrapUp();
  }
}

async function wrapUp() {
  if (!callId) return;
  const id = callId;
  callId = null;
  ending = true;
  window.clearInterval(timerId);
  conversation = null;
  let outcome = scamCaught ? "ended_scam" : "message";
  try {
    const r = await fetch(`${API}/calls/web/${id}/end`, { method: "POST" });
    outcome = (await r.json()).outcome ?? outcome;
  } catch { /* backend down: show what the page saw */ }
  const copy: Record<string, [string, string]> = {
    ended_scam: ["Scam caught", "Guardian ended the call, saved the evidence and texted Linda's family."],
    connected: ["Call ended", "Guardian heard nothing suspicious. The recording was deleted."],
    message: ["Call ended", "Guardian heard nothing that crossed the scam line. The recording was deleted."],
  };
  const [title, text] = copy[outcome] ?? copy.message;
  finish(outcome, title, text);
}

function finish(outcome: string, title: string, text: string) {
  el.resultIcon.dataset.outcome = outcome;
  el.resultTitle.textContent = title;
  el.resultBody.textContent = text;
  show("result");
}

// Opened inside the landing page's call overlay: drop the page backdrop.
if (new URLSearchParams(location.search).has("embed")) document.documentElement.classList.add("embed");
// Overlay closed or tab gone mid-call: still let the backend decide and log the call.
window.addEventListener("pagehide", () => {
  if (callId) navigator.sendBeacon(`${API}/calls/web/${callId}/end`);
});

el.call.onclick = placeCall;
el.hangup.onclick = hangUp;
el.again.onclick = () => show("dial");
renderPresets();
show("dial");
