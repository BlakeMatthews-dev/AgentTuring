# Changelog

All notable changes to Stronghold are documented here.

## Unreleased

- Added `SessionCheckpoint` type, `CheckpointStore` protocol, `InMemoryCheckpointStore`, and admin read endpoints at `/v1/stronghold/admin/checkpoints[/{id}]` (S1.3). Schema is byte-compatible with the client-side `/checkpoint-save` skill for forward ingestion.
