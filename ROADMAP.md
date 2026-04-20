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

## 2. Claude Agent SDK hook integration

### What this buys

Sentinel currently runs at `git push` time. The Claude Agent SDK
(`anthropics/claude-agent-sdk-python`, released 2025) exposes
pre-tool-call and post-tool-call hooks that fire *inside* an agent's
execution loop — much finer granularity than a pre-push hook.

Use cases:

- Block a `Write` tool call that would modify a `sentinel:skip-file`-
  marked file when the agent has no justification.
- Run `baseline diff` *before* the agent commits, not after — prevents
  drift from ever landing in a commit.
- Fire on `Bash` tool calls that try to `SENTINEL_BYPASS=1 git push`,
  log the attempt even when the hook would normally permit bypass.

### Design

Wrap Sentinel's rule set in a hook adapter:

    from claude_agent_sdk import ClaudeAgent
    from sentinel.adapters import sentinel_pretool_hook

    agent = ClaudeAgent(
        pre_tool_call=sentinel_pretool_hook(
            rules=["P0-hardcoded-local-path", "P0-baseline-drift"],
            repo_root="."
        ),
    )

### Blocked on

Claude Agent SDK's hook API stability. As of 2026-04-20 the SDK is
active development; hook contract may change. Better to wait for
1.0 release before building the Sentinel adapter. Worth 1 week.

### Why deferred

SDK not yet 1.0, so building against it risks rework. Adapter is
speculative until a real use case surfaces where push-time enforcement
isn't enough.

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
