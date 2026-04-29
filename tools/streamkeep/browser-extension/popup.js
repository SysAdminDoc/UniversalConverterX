// StreamKeep Companion popup. Stores host/port/token in chrome.storage.local,
// fires authenticated POST /send_url to the app's local server.

const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function setStatus(msg, cls) {
  statusEl.className = "status " + (cls || "");
  statusEl.textContent = msg || "";
}

async function load() {
  const cfg = await chrome.storage.local.get(["host", "port", "token"]);
  if (cfg.host) $("host").value = cfg.host;
  if (cfg.port) $("port").value = cfg.port;
  if (cfg.token) $("token").value = cfg.token;
}

async function save() {
  const host = $("host").value.trim() || "127.0.0.1";
  const port = parseInt($("port").value, 10) || 0;
  const token = $("token").value.trim();
  await chrome.storage.local.set({ host, port, token });
  setStatus("Saved.", "ok");
}

async function currentTabUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab && tab.url ? tab.url : "";
}

async function companionCall(path, method, body) {
  const { host, port, token } = await chrome.storage.local.get([
    "host", "port", "token",
  ]);
  if (!host || !port || !token) {
    throw new Error("Set host, port, and token first.");
  }
  const url = `http://${host}:${port}${path}`;
  const resp = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

async function testPairing() {
  setStatus("Checking…");
  try {
    const r = await companionCall("/ping", "GET");
    setStatus(`Paired with ${r.app || "StreamKeep"}.`, "ok");
  } catch (e) {
    setStatus(`Test failed: ${e.message}`, "err");
  }
}

async function sendUrl(action) {
  setStatus("Sending…");
  try {
    const url = await currentTabUrl();
    if (!url || !/^https?:/.test(url)) {
      setStatus("Current tab has no http(s) URL.", "err");
      return;
    }
    await companionCall("/send_url", "POST", { url, action });
    setStatus(`Sent to ${action}.`, "ok");
  } catch (e) {
    setStatus(`Send failed: ${e.message}`, "err");
  }
}

async function sendAllTabs() {
  setStatus("Sending tabs…");
  try {
    const tabs = await chrome.tabs.query({});
    const urls = tabs
      .map((t) => t.url)
      .filter((u) => u && /^https?:/.test(u));
    if (urls.length === 0) {
      setStatus("No http(s) tabs found.", "err");
      return;
    }
    let ok = 0;
    for (const url of urls) {
      try {
        await companionCall("/send_url", "POST", { url, action: "queue" });
        ok++;
      } catch (_) {
        /* skip individual failures */
      }
    }
    setStatus(`Sent ${ok} of ${urls.length} tabs.`, ok > 0 ? "ok" : "err");
  } catch (e) {
    setStatus(`Send failed: ${e.message}`, "err");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("save").addEventListener("click", save);
  $("test").addEventListener("click", testPairing);
  $("send-fetch").addEventListener("click", () => sendUrl("fetch"));
  $("send-queue").addEventListener("click", () => sendUrl("queue"));
  $("send-all-tabs").addEventListener("click", sendAllTabs);
});
