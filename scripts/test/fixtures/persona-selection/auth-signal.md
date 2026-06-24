# Fixture: auth signal fires security gate

## Summary

Add JWT session validation to the login flow.

## Requirements

- R1: Validate `jwt` on every authenticated request.

<!-- expected-personas: core + security (matched: jwt) -->
