# LipSight (sidecar)

UCX module: **Lip Reading**
Phase: **v2.1**

## What lands here

A vendored, frozen copy of [LipSight](https://github.com/SysAdminDoc/LipSight) — Visual speech recognition.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.1. Source lives at `~/repos/LipSight/` until then.
