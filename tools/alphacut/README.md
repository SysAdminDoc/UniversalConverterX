# AlphaCut (sidecar)

UCX module: **Background Remover**
Phase: **v2.1**

## What lands here

A vendored, frozen copy of [AlphaCut](https://github.com/SysAdminDoc/AlphaCut) — AI segmentation, ProRes/WebM alpha, batch.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.1. Source lives at `~/repos/AlphaCut/` until then.
