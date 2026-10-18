/**
 * Browser phone: stands in for a real phone line so the demo needs no Twilio.
 *
 * 1. POST /calls/web/start with the caller number -> route (verified / rejected / screen).
 * 2. Screened calls open an ElevenLabs session from the signed URL. The agent's `assess`
 *    client tool runs here and posts to /tools/assess (CONTRACTS section 6), so the backend
 *    needs no public URL for live scoring.
 * 3. On end / connect the agent says its line, then the page hangs up and calls /calls/web/{id}/end.
 */
import { Conversation } from "@elevenlabs/client";

const API = (import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/$/, "");
const HARD_STOP_S = 90;

// CONTRACTS section 4 demo numbers, plus two unknown callers for screening.
const PRESETS = [
  { label: "Unknown caller", hint: "Gets screened", number: "+12135550177" },
  { label: "Pharmacy (unknown)", hint: "Gets screened", number: "+18185550123" },
  { label: "Son (David)", hint: "Verified, rings through", number: "+13105550111" },
  { label: "Flagged scam number", hint: "Score 92, rejected", number: "+12135550142" },
];

type Action = "continue" | "end" | "connect" | "message";
type Assess = { action: Action; risk: number; say: string };

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
let decided: Action | null = null;
let lastAgent = "";
let lastCaller = "";
let timerId: number | undefined;
let stream: EventSource | null = null;
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

function addTurn(who: "agent" | "caller", text: string) {
  const li = document.createElement("li");
  li.className = who;
  li.innerHTML = `<span>${who === "agent" ? "Guardian" : "You"}</span>`;
  li.append(document.createTextNode(text));
  el.transcript.append(li);
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

function watchFlags(id: string) {
  stream = new EventSource(`${API}/stream/live`);
  stream.addEventListener("score", (e) => {
    const ev = JSON.parse((e as MessageEvent).data);
    if (ev.call_id !== id) return;
    el.flags.replaceChildren(...(ev.data.red_flags as string[]).map((f) => {
      const li = document.createElement("li");
      li.textContent = f;
      return li;
    }));
  });
}

async function assess(params: { guardian_asked?: string; caller_said?: string }): Promise<string> {
  if (!callId) return JSON.stringify({ action: "continue", say: "" });
  try {
    const r = await fetch(`${API}/tools/assess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        call_id: callId,
        caller_number: callNumber,
        guardian_asked: params.guardian_asked || lastAgent,
        caller_said: params.caller_said || lastCaller,
      }),
    });
    const out: Assess = await r.json();
    setRisk(out.risk);
    if (out.action !== "continue") {
      decided = out.action;
      el.liveStatus.textContent = { end: "Ending call…", connect: "Connecting to Linda…",
                                    message: "Taking a message…" }[out.action];
      if (out.action !== "message") window.setTimeout(hangUp, 12000); // backstop if no mode change
    }
    return JSON.stringify({ action: out.action, say: out.say });
  } catch (err) {
    console.error("assess failed", err);
    return JSON.stringify({ action: "continue", say: "" });
  }
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

    await startScreening(body.signed_url, body.dynamic_variables);
  } catch (err) {
    el.dialError.textContent = `Couldn't place the call: ${(err as Error).message}`;
    el.dialError.hidden = false;
  } finally {
    el.call.disabled = false;
  }
}

async function startScreening(signedUrl: string, dynamicVariables: Record<string, string>) {
  decided = null;
  ending = false;
  lastAgent = lastCaller = "";
  el.transcript.replaceChildren();
  el.flags.replaceChildren();
  setRisk(0);
  el.liveNumber.textContent = callNumber;
  el.liveStatus.textContent = "Connecting…";
  show("live");
  watchFlags(callId!);

  conversation = await Conversation.startSession({
    signedUrl,
    dynamicVariables,
    clientTools: { assess },
    onConnect: () => {
      el.liveStatus.textContent = "Guardian is screening this call";
      startTimer();
    },
    onMessage: ({ message, role }) => {
      if (role === "agent") lastAgent = message;
      else lastCaller = message;
      addTurn(role === "agent" ? "agent" : "caller", message);
    },
    onModeChange: ({ mode }) => {
      // The agent has finished its closing line: hang up like a phone would.
      if (mode === "listening" && (decided === "end" || decided === "connect")) hangUp();
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
  stream?.close();
  conversation = null;
  const seen: Record<string, string> = { end: "ended_scam", connect: "connected" };
  let outcome = seen[decided ?? ""] ?? "message";
  try {
    const r = await fetch(`${API}/calls/web/${id}/end`, { method: "POST" });
    outcome = (await r.json()).outcome ?? outcome;
  } catch { /* backend down: show what the page saw */ }
  const copy: Record<string, [string, string]> = {
    ended_scam: ["Scam call ended", "Guardian hung up. Evidence saved and the family was texted."],
    connected: ["Connected to Linda", "Low risk. Linda heard a short whisper, then the call. Recording deleted."],
    message: ["Message taken", "Guardian wasn't sure, so it took a message for Linda. Recording deleted."],
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
