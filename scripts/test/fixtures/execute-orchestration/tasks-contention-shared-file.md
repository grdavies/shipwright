---
topic: contention-fixture
frozen: true
---

# Contention fixture

### 1. Shared file phase (S)

- [ ] 1.1 Edit shared module
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** first change
- [ ] 1.2 Update shared module
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** second change serializes on shared file
