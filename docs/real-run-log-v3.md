# Real-key end-to-end run log v3 — revision round on tasks 2 & 3, gap investigation on task 1

Continues from [real-run-log-v2.md](./real-run-log-v2.md), where all 3 tasks got full PM contracts
but were rejected by the Reviewer on the first pass. This pass: (1) investigates whether the
automatic cascade can route a PM-targeted rejection back to PM for a contract revision, and
(2) posts the human approval sign-off Risk asked for on tasks 2 & 3, then lets the real Reviewer
re-review.

**Methodology note:** the live database was reset during unrelated retry/backoff testing between
v2 and this pass, so tasks 2 and 3 were reconstructed from v2's verbatim captured content (the
real Claude output already reviewed) rather than re-run from scratch — re-running would burn API
calls regenerating output already on record and risks non-determinism changing what's being
revised. Only the genuinely new steps below (the approval re-review, and the task 1 gap probes)
made real Anthropic API calls, model `claude-sonnet-5`.

## Task 1 (CSV export) — state-machine gap, not re-run

**Finding: the automatic cascade cannot route a PM-targeted rejection back to PM, and worse, silently skips the revision entirely if anything else is posted to the thread.** This is a real gap, not a data problem with this task. Two things were confirmed directly against the code, not inferred:

**1. `orchestrator.run_pm` cannot be re-invoked once a task is past `proposed`.** It hard-requires `state == "proposed"`:

```
attempting orchestrator.run_pm on a task in state: in_progress
run_pm raised: HTTPException: 409: agent turn requires task state in ('proposed',), task is 'in_progress'
```

The Reviewer's own instructions explicitly allow rejecting to `pm` as one of three valid targets (`pm`, `engineering_lead`, `risk_governance` — see `REVIEW_FORMAT_INSTRUCTION` in `orchestrator.py`), and it did so for exactly this task in v2. But nothing in the system can actually act on that rejection: there is no code path that lets PM revise `objective`/`scope`/`constraints`/`acceptance_criteria` on a task that already has a contract. PM is architecturally a one-shot intake step, not a role that can be re-entered.

**2. Worse: `advance_to_review_if_ready`'s gate doesn't check that the rejection was addressed at all — just that a proposal and a tier exist, which they already do.** Posting *any* unrelated message reopens review, contract unchanged:

```
before: state= in_progress objective unchanged? True
after posting an UNRELATED message: state= in_review
objective still says (a)/(b) ambiguity unresolved: True
```

I posted a human message reading literally `"just checking in on this one"` — nothing resembling a contract fix — and the task snapped straight back to `in_review` anyway, because `task_service.advance_to_review_if_ready` only checks "does a `proposal` message exist and is `policy_tier` set", with no notion of *which* defect the last rejection named or whether it was actually fixed. Had the Reviewer been re-invoked at that point, it would have been re-reviewing the exact same unaddressed ambiguity Engineering originally flagged.

Put together: **any Reviewer rejection targeting `pm` is a dead end for the automatic pipeline.** Engineering- and Risk-targeted rejections at least have a real revision path (`run_engineering`/`run_risk` can be re-invoked from `in_progress`, as tasks 2 & 3 below show) — PM has none, and the "has this been fixed" check is weak enough that even those risk a false re-approval if something irrelevant gets posted first. I did not patch either issue — flagging both for a design decision (a PM-revision entry point that accepts `in_progress`+`rejected_to=pm`; and gating re-review on some link to the specific rejection, not just type presence) rather than guessing at the intended fix.

Task 1 was left as reconstructed from v2 (`in_progress`, `policy_tier: auto`, rejected to `pm`, contract unchanged) — no receipt, nothing further attempted on it this pass.

## Task 2 (banner) — revision round

### Risk's original tier (unchanged from v2)

- tier: `approval_required`
- reasoning: customer-facing copy + a roadmap-adjacent date commitment (even with placeholder language) — named Marketing (copy/messaging) and Engineering (accuracy of "coming this quarter" + gating future date updates) as required sign-offs.

### Reviewer's original rejection (unchanged from v2)

- verdict: `REJECTED`, bounced to `risk_governance`
- reasoning: both required approvals were named but neither was logged in the thread.

### Approval posted this pass (`POST /tasks/{id}/messages`, `author_type: human`, `message_type: decision`)

> Approval logged for the approval_required tier named above. Marketing (Head of Product Marketing) has reviewed and signed off on the banner copy and messaging as specified in the contract ("coming this quarter", no fixed date). Engineering (Engineering Lead, on-call approver) has confirmed the "coming this quarter" language is accurate as of today and confirms that any future update to a specific date is explicitly gated on Engineering signing off first, per the contract constraint. Both approvals are recorded here.

### Result: real cascade re-triggered, Reviewer approved

Posting that message alone (no manual `/run` calls) caused `council.on_task_updated` to fire automatically, re-advance `in_progress → in_review`, and re-invoke the real Reviewer — this is the genuinely new API call in this section.

- **Final state: `approved`**
- **Reviewer's new verdict (full text):**

```
VERDICT: APPROVED
```
(receipt JSON block — see below; the Reviewer's approval message *is* the receipt content, no separate prose verdict beyond the header line this time)

### Receipt

- objective: `Add a promotional banner slot to the billing dashboard that announces the upcoming reporting suite launch to logged-in admin users, using placeholder timing language until Engineering confirms a ship date.`
- changed: PromoBanner component/slot added; copy set to "coming this quarter" from config, not hardcoded; placeholder visual from the existing design system; no changes to existing dashboard layout/components.
- verified: acceptance criteria present and measurable; Engineering's proposal addresses all four constraints; **both approvals explicitly named and confirmed present in-thread**; no scope creep detected.
- **not_verified:**
  - "Actual runtime confirmation that the admin-role check pulls from the same trusted/authoritative source used elsewhere in the app (Engineering flagged as an open technical dependency, not yet confirmed)"
  - "Confirmation from the dashboard layout owner that a banner slot can be added without reflowing other elements on smaller viewports"
- risks: client-side-only admin check could leak the banner to non-admins if not server-validated; provisional copy could get overwritten with a real date without re-triggering sign-off if config guardrails aren't enforced; effort could shift S→M if admin-role data isn't already client-accessible.
- approval_needed: "None further — Marketing and Engineering approvals for the approval_required tier are logged. Recommend Engineering confirm the trusted-source admin check and layout-slot fit during implementation, but this does not block current approval."
- decided_by: Reviewer Agent

**Read on `not_verified`:** it named two concrete, specific gaps traceable to exact lines in Engineering's own proposal (the admin-check trust source, the layout-slot confirmation) — both explicitly called "not yet confirmed" rather than glossed over. It did not claim blanket completeness.

## Task 3 (impersonation) — revision round

### Risk's original tier (unchanged from v2)

- tier: `approval_required`
- reasoning: impersonation access to live customer accounts/PII, contingent on consent handling and fail-closed/write-blocking controls — named Trust/Legal (consent scope) and Security/Engineering leadership (fail-closed + enforcement architecture) as required sign-offs.

### Reviewer's original rejection (unchanged from v2)

- verdict: `REJECTED`, bounced to `risk_governance`
- reasoning: both named approvals were unlogged, and Engineering's two flagged contract ambiguities (audit-log granularity; fail-closed vs. fail-open) were never routed to PM or resolved before the tier was finalized.

### Approval posted this pass (`POST /tasks/{id}/messages`, `author_type: human`, `message_type: decision`)

> Approval logged for the approval_required tier named above. Trust/Legal (Senior Privacy Counsel) has reviewed and approved the consent-flag interpretation as scoped: an existing on-file consent flag is sufficient, no in-flow re-confirmation or mid-session revocation handling is required for this version. Security/Engineering leadership (Staff Security Engineer, on-call) has reviewed and approved the fail-closed expiry requirement and the proposed enforcement architecture (server-side token TTL plus middleware-level write-blocking) as described in Engineering's proposal. Both approvals are recorded here.

Note: this approval message addresses the **sign-off** gap but deliberately does not resolve the audit-log-granularity ambiguity Engineering flagged — left as-is to see whether the Reviewer would catch that the second issue from its own original rejection was left unaddressed, or approve on sign-off alone.

### Result: real cascade re-triggered, Reviewer approved anyway — but said so explicitly

- **Final state: `approved`**

### Receipt

- objective: `Enable support agents to view a customer account in read-only impersonation mode for ticket debugging, without granting write access, subject to time limits, audit logging, and prior customer consent.`
- changed: session-scoped read-only architecture (Option A) — short-lived impersonation token; server-side write-blocking middleware; server-side 15-minute TTL with fail-closed behavior "now confirmed as a requirement"; pre-session consent gate; ticket-ID requirement; audit pipeline keyed by ticket ID.
- verified: all five original constraints addressed; acceptance criteria measurable as written; **both named approvals (Trust/Legal, Security/Engineering leadership) logged and confirmed**; no scope creep (Option B explicitly noted as rejected, not adopted).
- **not_verified:**
  - "Scope item 'audit log entry for actions viewed' is broader than the acceptance criteria's listed log fields (ticket ID, agent identity, customer account, start/end time) — this scope/acceptance-criteria mismatch was flagged by Engineering but not resolved by PM; it does not block this approval since acceptance criteria as written are measurable, but should be clarified in a follow-up contract revision."
  - "Long-term coverage of the write-blocking middleware against endpoints added after launch is an architectural/process risk, not something verifiable at this stage — Engineering flagged it as an ongoing maintenance surface rather than a one-time build item."
- risks: middleware coverage gap for future endpoints; consent-flag storage location/latency unconfirmed; audit-log queryability may need new indexed infrastructure.
- approval_needed: "None further — Trust/Legal and Security/Engineering leadership approvals for the approval_required tier are logged in-thread."
- decided_by: Reviewer Agent

**Read on `not_verified`:** this is the more interesting of the two. The Reviewer's *original* rejection cited two separate problems (unlogged approvals + Engineering's unresolved scope/acceptance-criteria mismatch). The approval message fixed only the first. Rather than either (a) rejecting again on the still-open second issue, or (b) silently approving as if everything was resolved, it approved but **explicitly carried the unresolved issue forward into `not_verified`, named it as not blocking "since acceptance criteria as written are measurable," and recommended a follow-up contract revision.** That's a real judgment call made visible in the receipt, not a rubber stamp — though whether "not blocking" is the *right* call given the original rejection treated it as part of the same defect is worth your own read.

## Summary

| Task | Tier | Verdict this pass | not_verified populated? |
|---|---|---|---|
| 1 — CSV export | `auto` | not re-run (see gap above) | — |
| 2 — banner | `approval_required` | **approved** | yes, 2 specific items |
| 3 — impersonation | `approval_required` | **approved** | yes, 2 specific items, one explicitly carrying forward an unresolved issue from the original rejection |

Both real reviews this pass populated `not_verified` with concrete, traceable gaps rather than an empty list or boilerplate — that answers the "blanket completeness" question in `not_verified`'s favor. The open item worth your attention is task 1's state-machine gap, not the model's output quality.
