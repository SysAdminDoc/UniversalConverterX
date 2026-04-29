# HEICShift (sidecar)

UCX module: **Image Converter**
Phase: **v2.2**

## What lands here

A vendored, frozen copy of [HEICShift](https://github.com/SysAdminDoc/HEICShift) — JPEG/PNG/HEIC/AVIF/JXL/RAW conversion.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.2. Source lives at `~/repos/HEICShift/` until then.
