# Fixture: billing-routing floors tier, not security persona

## Summary

Integrate Stripe subscription event delivery for Paddle migration path.

## Requirements

- R1: Handle `stripe` and `paddle` `subscription` events.

## Scope

Provider event routing only. No trust-boundary changes.

<!-- expected-personas: core-only (stripe/paddle/subscription are billing-routing, not security gate) -->
