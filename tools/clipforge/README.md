# ClipForge (sidecar)

UCX module: **Video Editor**
Phase: **v2.0**

## What lands here

A vendored, frozen copy of [ClipForge](https://github.com/SysAdminDoc/ClipForge) — Trim, crop, upscale, filter, audio, batch.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.0. Source lives at `~/repos/ClipForge/` until then.
