# FrameSnap (sidecar)

UCX module: **Frame Snapshot**
Phase: **v2.2**

## What lands here

A vendored, frozen copy of [FrameSnap](https://github.com/SysAdminDoc/FrameSnap) — Precise frame extraction.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.2. Source lives at `~/repos/FrameSnap/` until then.
