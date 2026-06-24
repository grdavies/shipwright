# Fixture: polysemous tokens alone do not fire design

## Summary

Backend materialized view and component boundaries refactor.

## Requirements

- R1: Split monolithic `view` into bounded `component` modules.
- R2: Normalize `page` cache keys in the `form` serializer.

## Scope

No user-facing UI. Database and service layer only.

<!-- expected-personas: core-only (component/view/page/form polysemous — no design gate) -->
