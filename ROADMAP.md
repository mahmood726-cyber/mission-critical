# MissionCritical Roadmap

Captured design for items deliberately deferred from the v0.2 release.
Each is adjacent to MissionCritical but substantial enough that
half-shipping would be worse than not shipping. Add at v0.3+ after the
methods paper has a target venue.

## 1. Pluggable CertBundle signers (HMAC → Ed25519/Sigstore) — SHIPPED 2026-04-18

### Status

Shipped in `overmind/verification/signers.py` + refactored `cert_bundle.py`.
Three signing methods, selected per-environment:

- **Ed25519** (preferred default): local keypair, no shared secret, works
  offline. The Windows-laptop-scheduled-task case that blocked cosign OIDC
  plumbing in the original roadmap entry. Private key on disk (chmod 600 on
  POSIX), public key embedded in each signed bundle.
- **HMAC-SHA256**: legacy, retained for backward-compat with archived
  nightly outputs. Deprecated-not-removed.
- **Sigstore keyless** (CI / release only): keeps the original cosign path
  for environments that *do* have OIDC identity plumbing (GitHub Actions).

Selection precedence (see `signers.select_signer()`):

1. Explicit `OVERMIND_SIGN_METHOD=ed25519|hmac|sigstore|none`
2. `OVERMIND_ED25519_KEY` set → Ed25519
3. `TRUTHCERT_HMAC_KEY` set → HMAC
4. `SIGSTORE_ID_TOKEN` set → Sigstore
5. Unsigned (logged warning, dev-mode only)

### Tests

32 tests across `test_signers.py` (16) + `test_cert_bundle_signers.py` (9)
+ `test_cert_bundle_hmac.py` (7, preserved untouched for regression).

### What was NOT done vs original roadmap

The "dual-sign + parallel-verify migration" proposed in the original
roadmap entry was skipped. The new design is strictly additive: existing
HMAC-signed bundles on disk still verify (legacy-method fallback), and
there are no HMAC bundles to migrate off of once a deployment flips to
Ed25519. Net: 1 focused session, not 1 focused day, because Ed25519
removed the blocker (no OIDC plumbing needed on Windows laptop).

---

## 2. Claude Agent SDK PreToolUse hook adapter — SHIPPED 2026-04-18

### Status

Shipped in `sentinel/adapters/claude_agent_hooks.py` (`Sentinel@3062e60`).
Originally deferred pending SDK 1.0; SDK 0.1.63's PreToolUse hook API
(`HookMatcher`, `PreToolUseHookInput`, `SyncHookJSONOutput`,
`PreToolUseHookSpecificOutput`) is stable enough to adapt to now.

Tool coverage (Write, Edit, Bash), with the ported checks:

- **P0-hardcoded-local-path** — regex on proposed file content (Write)
  or `new_string` (Edit), same YAML rule pattern, same excluded-path
  list (wiki/, tests/, data/nightly_reports/, …).
- **P0-placeholder-hmac** — blocks `SIG_RSA_SHA256_PLACEHOLDER`-style
  stubs that claim signed-ness without delivering.
- **P0-claude-config-committed** — blocks Write/Edit into `.claude/`
  (allows the gitignored `.claude/settings.local.json`).
- **P0-sentinel-bypass-attempt** (NEW) — blocks
  `SENTINEL_BYPASS=1 git push` in Bash calls inside the agent loop.
  The pre-push hook logs the bypass but still allows; catching it in
  the SDK loop gives the agent a chance to diagnose rather than
  quietly shipping a violation.

### Design choices

- Single async callback factory `sentinel_pretool_hook()` — users
  register it via `HookMatcher(matcher="Write|Edit|Bash", hooks=[...])`.
- No dependency on the SDK at import time (`claude-agent-sdk` is a
  declared-optional dep). Sentinel's core test path stays SDK-free.
- Emits BOTH legacy `decision="block"` + modern
  `hookSpecificOutput.permissionDecision="deny"` for SDK-version
  tolerance.
- Fails open on internal exceptions — a buggy rule must not wedge an
  agent run. Log loudly, allow the call.
- Respects `sentinel:skip-file` markers.

### What was NOT done vs original roadmap

- Portfolio-wide / cross-file rules (registry drift, blueprint-match)
  still only run at push-time. PreToolUse is per-tool-call; those need
  full repo context and would waste work on every tool call.
- PostToolUse hook (inspect what the agent actually wrote) not
  included — add only if a gap opens where a violation bypasses the
  pre-call check.
- `baseline diff` integration from the roadmap sketch is deferred.
  Baseline drift is a repo-scan check; wiring it into PreToolUse would
  require keeping an in-memory baseline cache per agent session. Real
  use case hasn't surfaced yet.

### Tests

36 tests: 32 unit (content checks + async dispatch + fail-open) + 4
integration (SDK-shape-conformance, skipped when SDK not installed).
Sentinel suite: 390 pass / 1 skip (was 354 pre-adapter).

---

## 3. Full `soda-core` adoption for provenance drift

### What this would replace

`provenance diff` — currently a hand-rolled per-key comparator.

### Why deferred

Current implementation is 20 LOC and works. `soda-core` is 80 MB of
dep surface for YAML-driven data-quality checks — overkill for
flagging whether `NCT00095238.N` drifted from 8442 to 1807. Adopt
only if provenance scope expands to CSV-level schema validation
(columns, types, null counts), which isn't in scope today.

---

## Shipped in v0.2

These were "future work" at v0.1 and now complete:

- Random-effects pooling (DL, REML, HKSJ) in diffmeta — done 2026-04-19
- SMD + GEN measures in diffmeta — done 2026-04-19
- Sentinel P0-baseline-drift plugin — done 2026-04-19
- Overmind NumericalContinuityWitness wired into tier-3 verify path — done 2026-04-19
- YAML tolerance registry (ESMValTool pattern) — done 2026-04-20
- Persistent claim-IDs (HEPData pattern) — done 2026-04-20
- W3C PROV-O export for provenance — done 2026-04-20
- RO-Crate 1.2 export for baseline + provenance — done 2026-04-20
- pytest-regressions bidirectional interop — done 2026-04-20
