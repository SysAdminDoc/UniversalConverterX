# Video Subtitle Remover (sidecar)

UCX module: **Subtitle Remover**
Phase: **v2.1**

## What lands here

A vendored, frozen copy of [Video Subtitle Remover](https://github.com/SysAdminDoc/Video Subtitle Remover) — AI hard-coded subtitle removal.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.1. Source lives at `~/repos/Video Subtitle Remover/` until then.
