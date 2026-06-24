# verify adapter: `playwright`

Runs `npx playwright test` when a Playwright config file exists at repo root. Skips (non-blocking) when absent.

Optional `verifyE2e.routes` in config supplies a `--grep` hint for affected-route smoke. Full suite runs when
routes are empty.

Logs tee to `/tmp/pf-verify.e2e.log`.
