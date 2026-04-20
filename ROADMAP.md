# MissionCritical Roadmap

Captured design for items deliberately deferred from the v0.2 release.
Each is adjacent to MissionCritical but substantial enough that
half-shipping would be worse than not shipping. Add at v0.3+ after the
methods paper has a target venue.

## 1. Replace HMAC with `sigstore/cosign` keyless signing

### What this replaces

Overmind's TruthCert bundles are currently HMAC-signed with a secret
read from `TRUTHCERT_HMAC_KEY`. The 2026-04-19 security review found:

- Key wasn't actually set in the Task Scheduler environment, so the
  "policy says signed, reality ships unsigned" failure mode was live.
- Shared-secret keys don't scale beyond one user, and the `lessons.md`
  entry *Cryptography / Signing (2026-04-14)* already documents that
  HMAC-key-from-bundle is a forgery vector.

### Design

Replace HMAC with `cosign sign-blob` using OIDC keyless mode. cosign
authenticates the signing identity against a trusted OIDC provider
(GitHub, Google, etc.) and uses the ephemeral-key transparency log
(Rekor) for public verification. No shared secret to leak.

Implementation sketch:

    # Producer (Overmind nightly):
    cosign sign-blob --bundle bundle.sig \
        --identity-token "$OIDC_TOKEN" \
        overmind-bundle.json

    # Consumer (anyone verifying the bundle):
    cosign verify-blob \
        --bundle bundle.sig \
        --certificate-identity <expected-subject> \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com \
        overmind-bundle.json

Python glue: `python-sigstore` (https://pypi.org/project/sigstore/)
provides the same primitives as the `cosign` CLI. Estimate: ~200 LOC
in `overmind/verification/cert_bundle.py`, replacing the HMAC compute
+ the `TRUTHCERT_HMAC_KEY` env read.

### Migration

1. Generate both HMAC and cosign signatures in parallel for one
   release cycle.
2. Verify-in-CI that both agree on identity (`<some wrapper comparing
   the two>`).
3. Drop HMAC; cosign becomes canonical.

### Estimated effort

1 focused day. Out-of-scope blocker is OIDC identity plumbing on a
Windows-laptop scheduled task, which requires a GitHub App or personal
access token flow.

### Why deferred

Not a single-session task. Current HMAC implementation is functional
when the key is set. Priority is lower than the methods-paper path.

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
