---
frozen: true
topic: contention-serial
---
### 1. One
- **File:** `shared/x.ts`
### 2. Two
- **File:** `shared/y.ts`
## Phase Dependencies
| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
