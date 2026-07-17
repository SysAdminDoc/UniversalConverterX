# Offline C2PA inspector

This optional sidecar uses `c2patool` 0.27 or newer to inspect and validate
local C2PA Content Credentials. UCX does not install or download c2patool.

```powershell
$env:C2PATOOL_PATH = 'C:\Tools\c2patool.exe'
python .\tools\c2pa\sidecar.py inspect `
  --input .\signed.jpg --output .\credentials.json --mode manifest
```

Modes are `manifest` (validated JSON), `info`, `tree`, and `certs`. A local
binary `.c2pa` sidecar can be selected with `--external-manifest`.

The wrapper is deliberately read-only. It exposes none of c2patool's manifest,
create, update, remote, signer, or output-directory options. Every run supplies
isolated settings with remote-manifest and OCSP fetching disabled, no allowed
network hosts, a 32 MiB decompressed-manifest ceiling, and no inherited trust
list URLs. Reports and diagnostics are bounded, the child has a timeout, and
successful reports are promoted atomically. Offline signature validation can
confirm cryptographic integrity, but signer trust may remain unknown unless a
local trust list is added in a future explicitly designed workflow.
