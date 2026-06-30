# Agent guidance (Shipwright)

## Mock realism (PRD 039 R10)

- Prefer testing against real collaborators when cost is low; reserve mocks for boundaries (I/O, clock, network).
- Avoid mocking the unit under test; patch at the dependency edge only.
- When mocks dominate a test file, expect an **advisory** `over_mock_scan` flag — refactor toward slimmer fakes.
- Keep mock setups readable: one behavior per test, explicit return values, no incidental `MagicMock` fan-out.

Run advisory scan:

```bash
python3 scripts/over_mock_scan.py --root .
```
