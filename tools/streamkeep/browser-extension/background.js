// Service worker — registers right-click context menu and handles sends.

async function companionPost(path, body) {
  const { host, port, token } = await chrome.storage.local.get([
    "host", "port", "token",
  ]);
  if (!host || !port || !token) return;
  const url = `http://${host}:${port}${path}`;
  await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send-link",
    title: "Send link to StreamKeep",
    contexts: ["link"],
  });
  chrome.contextMenus.create({
    id: "send-page",
    title: "Send page to StreamKeep",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  const url = info.linkUrl || info.pageUrl;
  if (!url || !/^https?:/.test(url)) return;
  companionPost("/send_url", { url, action: "queue" });
});
