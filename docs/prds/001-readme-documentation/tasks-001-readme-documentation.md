---
date: 2026-06-24
topic: readme-documentation
frozen: true
frozen_at: 2026-06-24
---

# Task list: PRD 001 — README and user documentation

**Amendment A1:** User docs in `documentation/` (not `docs/guides/`).

## 1. Scaffold user docs (R13, R14, R17, R18)

- [x] 1.1 Create `documentation/` directory (R18)
  - **File:** `documentation/`
  - **Expected:** directory exists; no files under `docs/` for user content
  - **R-IDs:** R18
- [x] 1.2 Add adopters vs dev pointer in CONTRIBUTING (R14)
  - **File:** `CONTRIBUTING.md`
  - **Expected:** links to `documentation/`; notes gitignored `docs/`
  - **R-IDs:** R14
- [x] 1.3 Confirm `.gitignore` unchanged and paths correct (R13)
  - **File:** `.gitignore`
  - **Expected:** `git check-ignore docs/prds/INDEX.md` ignored; `documentation/` not ignored
  - **R-IDs:** R13

## 2. Author guide files (R9, R10, R11)

- [x] 2.1 Write getting-started with three persona paths (R10)
  - **File:** `documentation/getting-started.md`
  - **Expected:** paths for new feature, quick fix, production incident; migration section
  - **R-IDs:** R10
- [x] 2.2 Write commands taxonomy table (R9)
  - **File:** `documentation/commands.md`
  - **Expected:** orchestrator + entry-point tables; ≤15 orchestrator/entry rows in primary tables
  - **R-IDs:** R9
- [x] 2.3 Use repository-relative links in guides (R11)
  - **File:** `documentation/*.md`
  - **Expected:** links use `../core/commands/` and sibling paths
  - **R-IDs:** R11

## 3. Rewrite README (R1–R8, R12, R15, R17)

- [x] 3.1 Hero with outcomes and trust line (R1)
  - **File:** `README.md`
  - **Expected:** tagline, three bullets, never auto-merges
  - **R-IDs:** R1
- [x] 3.2 Two-repo model and install quick start (R2, R3)
  - **File:** `README.md`
  - **Expected:** plugin install vs `/sw-setup` sections; 3-step install
  - **R-IDs:** R2, R3
- [x] 3.3 Prerequisites and target-repo config (R4, R5)
  - **File:** `README.md`
  - **Expected:** prerequisites list; `/sw-setup` and zero-config paths
  - **R-IDs:** R4, R5
- [x] 3.4 Routing table, tiers, workstream mermaid (R6, R7, R8)
  - **File:** `README.md`
  - **Expected:** when-to-use table; tier table; mermaid with Quick bypass
  - **R-IDs:** R6, R7, R8
- [x] 3.5 Footer links and length cap (R12, R15, R17)
  - **File:** `README.md`
  - **Expected:** `documentation/` links; `wc -l README.md` ≤ 150; CONTRIBUTING separate
  - **R-IDs:** R12, R15, R17

## 4. Verify and ship (R16)

- [x] 4.1 Manual link and length verification (R11, R15, R16)
  - **File:** `README.md`, `documentation/*.md`
  - **Expected:** relative links resolve; 60-second next-command walkthrough passes
  - **R-IDs:** R11, R15, R16

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 3.1 | README hero manual review |
| R2 | 3.2 | Two-repo model manual review |
| R3 | 3.2 | Install quick start manual review |
| R4 | 3.3 | First-run section manual review |
| R5 | 3.3 | Prerequisites manual review |
| R6 | 3.4 | Routing table manual review |
| R7 | 3.4 | Tier table manual review |
| R8 | 3.4 | Mermaid diagram manual review |
| R9 | 2.2 | documentation/commands.md orchestrator tables |
| R10 | 2.1 | getting-started persona paths manual review |
| R11 | 2.3, 4.1 | Relative link click-through |
| R12 | 3.5 | Footer separation manual review |
| R13 | 1.3 | git check-ignore docs/prds ignored |
| R14 | 1.2 | CONTRIBUTING.md documents documentation/ root |
| R15 | 3.5 | wc -l README.md ≤ 150 |
| R16 | 4.1 | 60-second next-command walkthrough |
| R17 | 3.5 | README links to documentation/*.md |
| R18 | 1.1 | no user docs under docs/ |
