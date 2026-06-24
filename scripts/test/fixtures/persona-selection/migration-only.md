# Fixture: migration-only floors tier, not security persona

## Summary

Run a schema migration and backfill historical rows.

## Requirements

- R1: Execute `migration` script with idempotent `backfill`.

## Scope

Data layer only. No trust-boundary changes.

<!-- expected-personas: core-only (migration/backfill are data-migration tags, not security) -->
