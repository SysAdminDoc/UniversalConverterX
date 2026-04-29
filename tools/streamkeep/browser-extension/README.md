# StreamKeep Companion (browser extension)

One-click "send current tab URL to StreamKeep desktop app."

## Install (Chrome / Edge — unpacked)

1. Visit `chrome://extensions`, enable **Developer mode**.
2. Click **Load unpacked**, pick this `browser-extension/` folder.
3. Pin the StreamKeep icon in the toolbar.

## Install (Firefox — temporary)

1. Visit `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on**, pick this `browser-extension/manifest.json`.

## Pair with StreamKeep

1. Open StreamKeep → **Settings** tab → **Browser companion**. Tick **Enable**.
2. The tab shows a **Pairing token** (32-char hex, regenerated every launch) and a port.
3. Click the StreamKeep browser icon, paste the token, enter the port, click **Save**.
4. Click **Test pairing** — should show `Paired with StreamKeep.`

## Send a URL

Open any supported page (Kick, Twitch, YouTube, Rumble, etc.), click the icon, then:

- **Send to Fetch** — StreamKeep jumps to the Download tab and fetches immediately.
- **Send to Queue** — Queued silently; StreamKeep shows a status toast.

## Security

- Server binds **strictly to 127.0.0.1** — never reachable over the network.
- Every request requires a bearer token compared in constant time.
- Tokens are **never stored on disk** — they regenerate each time you launch StreamKeep.
- Re-pairing is a paste-and-save; no re-install needed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Test failed: HTTP 401` | Token mismatch — re-copy from StreamKeep Settings. |
| `Test failed: Failed to fetch` | StreamKeep isn't running, or the companion server is off in Settings. |
| `Send failed: Current tab has no http(s) URL` | Extension pages (chrome://, about:…) can't be captured. |
