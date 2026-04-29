# VideoCrush (sidecar)

UCX module: **Compressor**
Phase: **v2.0**

## What lands here

A vendored, frozen copy of [VideoCrush](https://github.com/SysAdminDoc/VideoCrush) — Compress videos with FFmpeg + preset profiles.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.0. Source lives at `~/repos/VideoCrush/` until then.
