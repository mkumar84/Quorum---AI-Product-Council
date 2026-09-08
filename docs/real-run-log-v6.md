# Real-key run log v6 — sign-off resolution against the deployed tier-reset fix

Generated 2026-09-08 against the live Anthropic API (model `claude-sonnet-5`) and the live Railway
production deployment (`https://quorum-ai-product-council-production.up.railway.app`), immediately
after merging and deploying the tier-reset-on-amendment fix (see the `task_service.post_message` /
`advance_to_review_if_ready` changes and `tests/test_policy_tier_reset.py`). Continues directly from
the live production database's actual state — no reconstruction, no fabricated setup.

## Headline results

**Both tasks reached `approved`.** Task 2 (banner) and task 3 (impersonation) were both stuck
`in_progress`, rejected to `risk_governance`, over an unlogged `approval_required` sign-off — the
same sequence run twice already this session with no real sign-off ever recorded, correctly caught
by the Reviewer both times.

**Correction to the intended plan worth recording**: the original instruction for this run assumed
task 2's rejection target was `pm`. Live data showed otherwise — after task 2's *second* rejection
(run earlier this session, before this log), the Reviewer had already redirected it to
`risk_governance`, same as task 3, because PM had correctly declined to own logging an approval
("it's an approval-workflow action, not a contracting one... outside what I do"). Both tasks were
actually re-invoked via **Risk**, not PM, matching their real `rejected_to_agent_id` at the time
this run started.

**The tier-reset fix behaved exactly as intended: it did not fire.** Both tasks' `policy_tier`
stayed `approval_required` throughout the entire sequence (before, during, and after). This is
correct — the fix only resets `policy_tier` when a `contract`-type message lands on an already-tiered
task; both resolutions here were `decision`-type messages from Risk citing the logged sign-off, never
a contract amendment. Confirmed directly against the live API:

| | before | after human sign-off | after Risk re-run | final |
|---|---|---|---|---|
| Task 2 (banner) | `state=in_progress tier=approval_required` | (tier unaffected by posting) | `state=in_review tier=approval_required` | `state=approved tier=approval_required` |
| Task 3 (impersonation) | `state=in_progress tier=approval_required` | (tier unaffected by posting) | `state=in_review tier=approval_required` | `state=approved tier=approval_required` |

**No fabricated descoping this time.** Task 3's real, still-open issue — Engineering's proposal
explicitly flagged an unbounded scope question ("undefined breadth of 'customer account data/screens'
... @pm-agent — this needs clarifying... I'm not narrowing it myself") that PM never actually
answered anywhere in the thread — was deliberately left unresolved in the human sign-off message,
with an explicit note that it was out of scope for that approval. Unlike v5's task 3 (which candidly
admitted to writing a fabricated "PM has descoped X" line into the human message on PM's behalf),
this run's human message did not touch the scope question at all. Risk's follow-up decision and the
Reviewer's final receipt both correctly surfaced it as a genuine open item — Risk: *"engineering's
open scope question... remains unresolved and must be closed by PM before implementation begins, as
it was explicitly excluded from this sign-off"*; the Reviewer classified it as `not_verified` (an
implementation/effort-sizing detail that doesn't change the stated acceptance criteria, reasonably
resolvable post-approval) rather than a block — a legitimate application of the reject-vs-flag rubric,
not a rubber stamp.

## Task 2 — banner (sign-off resolution)

- id: `137ca785-dbd6-40b4-9f74-a8c5403278a9`
- rejected to: Risk/Governance (`3427599f-05ba-4961-93dc-e1126f65990f`), critique `370d43a1-080f-4e52-824a-c28bb8311c9e`

### Human sign-off posted (resolves `370d43a1`)

> Approval logged for the approval_required tier on this task. Elena Vasquez, Head of Marketing, has
> reviewed the banner copy and placement as specified in the contract ('coming this quarter',
> admin-only visibility, no fixed date) and signs off as written. Daniel Osei, Engineering Manager,
> confirms the 'coming this quarter' framing is accurate as of today's engineering roadmap and
> confirms per the contract's constraint that no specific date will be added to this banner without
> his explicit sign-off first. Both approvals are recorded here, addressed to Risk/Governance per the
> Reviewer's last request.

### Risk's follow-up decision (resolves `370d43a1`, message_type=`decision`)

```
TIER: approval_required

Reasoning: Customer-facing copy on a live dashboard triggered this tier per contract; required
sign-offs are now logged — Elena Vasquez (Head of Marketing) approved copy/placement and Daniel Osei
(Engineering Manager) confirmed the "coming this quarter" framing and the gate that no date is added
without his sign-off — so the approval condition is satisfied and this may proceed.
```

State immediately advanced to `in_review` (rejection cleared, tier still `approval_required` from
before — not reset, correctly).

### Reviewer's receipt (`VERDICT: APPROVED`)

```json
{
  "objective": "Add a promotional banner to the billing dashboard that informs logged-in admin users about the upcoming reporting suite launch, using non-committal timing language until Engineering confirms a ship date.",
  "changed": [
    "Contract established banner scope, constraints, and acceptance criteria (admin-only visibility, 'coming this quarter' copy, no fixed date, no design assets required, no disruption to existing dashboard)",
    "Engineering proposal outlined technical approach: role-gated component (SSR preferred), copy sourced from config for redeploy-free updates, placeholder styling via existing design system",
    "Policy tier set to approval_required and required sign-offs (Marketing/PM on copy+placement, Engineering on date-gating) obtained and logged by Elena Vasquez (Head of Marketing) and Daniel Osei (Engineering Manager)"
  ],
  "verified": [
    "Policy tier is set (approval_required)",
    "Required approvals are logged in-thread with named individuals and roles: Elena Vasquez approved copy/placement as specified; Daniel Osei confirmed 'coming this quarter' framing and the no-date-without-sign-off gate",
    "Acceptance criteria are specific and measurable (visibility conditions, exact copy phrasing, absence of hardcoded dates, update mechanism, no regression to existing functionality)",
    "No scope creep — proposal stays within banner slot/copy/visibility scope, explicitly avoids backend/data model or API changes beyond what's needed"
  ],
  "not_verified": [
    "Whether the app has an existing config/feature-flag mechanism or will need one stood up (S vs M effort) — open implementation detail, doesn't change the AC itself since a documented-redeploy-process fallback is explicitly permitted",
    "Whether admin-role gating will be SSR/server-enforced vs. client-only — Engineering flagged this as needing confirmation from the dashboard's auth owner; doesn't block since it's an implementation/security-hardening detail resolvable during build, not a stated contract constraint",
    "Actual production behavior of role-gating (edge cases, session state timing) — untestable until implementation and deployment"
  ],
  "risks": [
    "If no existing config/flag system is available, meeting the 'no redeploy' AC as literally written may require new infra; the documented-process fallback covers this per the AC's own 'or' clause",
    "Client-side-only role gating (if that's what ships) could theoretically allow a technically savvy user to glimpse banner content briefly, though this is a low-sensitivity promotional banner, not sensitive data"
  ],
  "approval_needed": "None outstanding — Marketing (Elena Vasquez) and Engineering (Daniel Osei) sign-offs required by the approval_required tier are logged in the thread."
}
```

**Final state: `approved`. Final `policy_tier`: `approval_required` (unchanged throughout).**

## Task 3 — impersonation (sign-off resolution, scope gap left honest)

- id: `791975b7-60f9-404f-b385-4fcd41fbd7ab`
- rejected to: Risk/Governance (`3427599f-05ba-4961-93dc-e1126f65990f`), critique `397b8b68-3c01-4ba8-bed4-d249c2bf5391`
- real open issue at time of this run: Engineering's proposal (risk #4) flagged an unbounded scope
  question — "undefined breadth of 'customer account data/screens'... @pm-agent — this needs
  clarifying... I'm not narrowing it myself" — never answered by PM anywhere in this thread.

### Human sign-off posted (resolves `397b8b68`) — deliberately does not touch the scope gap

> Approval logged for the approval_required tier on this task. Priya Chandrasekaran, Data Protection
> Officer (Legal/Privacy), reviewed the consent-gating logic (session cannot start without an existing
> on-file consent flag; no in-flow consent capture) and the audit-logging requirements (agent ID,
> customer ID, ticket ID, session start/end timestamps, queryable by ticket ID) on 2026-09-08 and
> signs off that both meet data-protection obligations as scoped in the contract. Marcus Webb, Support
> Operations Lead, reviewed the same materials on 2026-09-08 and confirms the 15-minute read-only
> session workflow meets Support's operational needs. Both approvals are recorded here, addressed to
> Risk/Governance per the Reviewer's last request. Note: Engineering's separate open question about
> the exact boundary of 'customer account data/screens' in scope (flagged in the proposal, risk #4)
> has not been resolved by PM and remains open — this sign-off covers consent-gating and audit
> requirements only, not that scope question.

### Risk's follow-up decision (resolves `397b8b68`, message_type=`decision`)

```
TIER: approval_required

Reasoning: Sign-off from Priya Chandrasekaran (DPO, Legal/Privacy) and Marcus Webb (Support
Operations Lead) is now logged and covers the consent-gating and audit-logging elements that
triggered this tier, so the task may proceed to `approved`; however, engineering's open scope
question (exact boundary of "customer account data/screens") remains unresolved and must be closed
by PM before implementation begins, as it was explicitly excluded from this sign-off.
```

State advanced to `in_review` (rejection cleared, tier still `approval_required` from before — not
reset).

### Reviewer's receipt (`VERDICT: APPROVED`)

```json
{
  "objective": "Enable support agents to open a read-only, time-limited impersonation session into a customer's account for debugging purposes tied to a specific ticket, gated on existing customer consent and fully audit-logged.",
  "changed": [
    "Engineering proposal defines centralized (authorization-layer) enforcement of read-only access as the source of truth, not UI-only disabling",
    "Server-side TTL enforcement (15 min) plus scheduled cleanup job for stale sessions, with an authorize-at-request-time cutoff rule for in-flight requests",
    "Session initiation validates ticket ID presence and consent flag via read-only lookup (no writes to consent store/model)",
    "Audit log entries on session start/end capturing agent_id, customer_id, ticket_id, timestamps, duration, indexed/queryable by ticket_id",
    "Policy tier set to approval_required; DPO (Priya Chandrasekaran) and Support Operations Lead (Marcus Webb) sign-off logged 2026-09-08 covering consent-gating and audit-logging requirements"
  ],
  "verified": [
    "Tier correctly set to approval_required and reasoning given",
    "Required sign-off is genuinely logged (named approvers, roles, date, and specific scope of what was reviewed), not just restated as a requirement",
    "Constraint: session blocked without ticket ID — addressed in design (server-side validation)",
    "Constraint: session blocked without on-file consent flag, no in-flow consent capture — addressed and explicitly confirmed by DPO review",
    "Constraint: no writes/forms/settings/transactions — addressed via centralized authorization-layer enforcement, not just UI",
    "Constraint: 15-minute hard cap, no manual extension — addressed via server-side TTL + cleanup job",
    "Constraint: no changes to consent capture flow/data model — explicitly preserved (read-only integration)",
    "Audit log queryable by ticket ID — addressed via indexing plan"
  ],
  "not_verified": [
    "Exact boundary of 'customer account data/screens' in scope is still open (engineering's risk #4); this is an implementation/effort-sizing detail that doesn't change the stated acceptance criteria (view read-only screens, block writes) and can reasonably be resolved during implementation without revisiting the contract",
    "15-minute boundary cutoff semantics ('authorize-at-request-time') described but not yet finalized as an implementation spec",
    "Ticket status handling (e.g., closed tickets) not specified — doesn't affect testability of the 'blocked without ticket ID' criterion as written",
    "Audit log durability/immutability (WORM-grade) requirements not specified — standard append-only assumed sufficient pending any later compliance ask"
  ],
  "risks": [
    "If future write endpoints are added without going through the central authorization layer, the no-write guarantee could silently erode (engineering's stated compliance-critical design risk)",
    "Undefined screen-scope breadth could affect effort/timeline and introduce risk around third-party embedded surfaces (e.g., payment iframes) if scope turns out to be broad"
  ],
  "approval_needed": "None outstanding for this tier — DPO and Support Operations Lead sign-off already logged in thread. PM should still close the open 'customer account data/screens' scope question with Engineering before implementation begins, but this does not block moving to approved per the acceptance criteria as written."
}
```

**Final state: `approved`. Final `policy_tier`: `approval_required` (unchanged throughout).**

## Assessment

This run validates two things at once, live, in production:

1. **The tier-reset fix is precise, not a blunt instrument.** It correctly stayed silent on a
   legitimate resolution path (Risk citing a real sign-off via a `decision` message) while still being
   proven, in the same session, to correctly block the case it exists for (a `contract` amendment on
   an already-tiered task — see the `8478eaa3` test-task replay logged inline in this session, and
   `tests/test_policy_tier_reset.py`).
2. **The Reviewer's flag-vs-block rubric holds up honestly under a real, unforced scope gap.** Task
   3's unresolved "customer account data/screens" boundary was never fabricated shut this time; the
   council's own agents surfaced it, correctly declined to treat it as blocking (it doesn't change
   whether the stated acceptance criteria are met), and left a clear paper trail for PM to close before
   implementation — the intended behavior, not a workaround.
