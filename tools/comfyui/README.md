# ComfyUI sidecar

`comfyui` submits a reviewed API-format workflow to an already running ComfyUI
server on `127.0.0.1`, `::1`, or `localhost`, waits for that exact prompt ID,
and atomically exports its output artifacts. It does not install ComfyUI,
download models or custom nodes, or support Comfy Cloud.

```powershell
comfyui.exe probe
comfyui.exe run --input workflow-api.json --output-dir result --accept-workflow
comfyui.exe run --input workflow-api.json --output-dir result `
  --accept-workflow --set '6.text="local prompt override"'
```

Export workflows with ComfyUI's **Export (API)** action. Start the separately
managed server with `--disable-api-nodes`. UCX rejects non-loopback endpoints,
redirects, embedded remote URLs, credential fields, and known cloud/network
node classes. Custom nodes are executable Python that UCX cannot audit, so each
run requires explicit workflow acknowledgment and should use only reviewed
local nodes.
