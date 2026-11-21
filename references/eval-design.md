# Eval Design Reference

## Contents

1. Architecture
2. Canonical case schema
3. Run-result schema
4. Metric catalog
5. Release-gate logic
6. Dataset lifecycle
7. Failure taxonomy
8. Statistical notes
9. Choosing thresholds
10. Multilingual evaluation
11. Fault injection and replay contract
12. Turn-level grader controls

## 1. Architecture

Use ports and adapters so the product owns the eval contract:

```text
Dataset repository -> Eval runner -> System-under-test adapter
                         |                    |
                         |                    -> sandbox/fixtures/record-replay
                         v
                  Grader strategies
                  - deterministic
                  - executable
                  - retrieval
                  - model judge
                  - human label import
                         |
                         v
                  Result repository -> CI gate/report/observability backend
```

Recommended interfaces:

```python
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TrialArtifact:
    output: Mapping[str, Any]
    trace: Sequence[Mapping[str, Any]]
    outcome: Mapping[str, Any]
    latency_ms: float
    token_count: int
    cost_usd: float


class SystemUnderTest(Protocol):
    async def run(self, case: Mapping[str, Any]) -> TrialArtifact: ...


class Grader(Protocol):
    def grade(
        self,
        case: Mapping[str, Any],
        artifact: TrialArtifact,
    ) -> Mapping[str, Any]: ...
```

Keep adapters around LangSmith, Braintrust, DeepEval, Ragas, OpenAI, or another backend. The canonical fixtures and results remain usable when vendors or model APIs change.

## 2. Canonical case schema

Use JSONL for portable datasets. One line is one case:

```json
{
  "id": "refund-denied-policy-001",
  "suite": "regression",
  "risk": "critical",
  "input": {
    "messages": [
      {"role": "user", "content": "Refund order A-100."}
    ]
  },
  "environment": {
    "fixture": "orders/v3/refund-denied.json",
    "clock": "2026-07-01T10:00:00Z",
    "identity": {"tenant_id": "tenant-a", "user_id": "user-1"}
  },
  "expected": {
    "outcome": {"order.A-100.status": "paid", "refund_count": 0},
    "required_tools": [
      {"name": "lookup_order", "arguments_subset": {"order_id": "A-100"}}
    ],
    "forbidden_tools": ["issue_refund"],
    "response_assertions": ["states_refund_is_not_allowed"],
    "rubric_id": "support-answer-v4"
  },
  "metadata": {
    "source": "production_incident",
    "source_ref": "redacted-incident-42",
    "tags": ["refund", "authorization", "negative-trigger"],
    "owner": "support-ai",
    "created_at": "2026-07-02",
    "dataset_version": "2026.07.0",
    "as_of": "2026-07-01",
    "pii_status": "redacted"
  }
}
```

Required fields are `id`, `suite`, `risk`, `input`, `expected`, and `metadata`. Use stable IDs; changing semantics creates a new ID. Keep `source_ref` opaque when it points to private records.

Recommended suites: `capability`, `regression`, `safety`, `production`, `judge-calibration`, `benchmark`.

Recommended risks: `critical`, `high`, `medium`, `low`.

## 3. Run-result schema

Persist each trial rather than only aggregate metrics:

```json
{
  "schema_version": "1.0",
  "run": {
    "run_id": "20260719-pr-183-a1b2c3",
    "started_at": "2026-07-19T08:00:00Z",
    "commit_sha": "a1b2c3",
    "dataset_version": "2026.07.0",
    "environment_version": "orders-fixtures-v3",
    "system": {
      "model": "provider/model-version",
      "prompt_version": "support-v17",
      "tool_schema_version": "tools-v9",
      "corpus_version": "kb-2026-07-18"
    },
    "grader_versions": {
      "outcome": "outcome-v2",
      "judge": "support-answer-v4@judge-model-version"
    }
  },
  "trials": [
    {
      "case_id": "refund-denied-policy-001",
      "trial": 1,
      "passed": true,
      "hard_failure": false,
      "scores": {
        "outcome": 1.0,
        "tool_selection": 1.0,
        "answer_quality": 0.9
      },
      "failure_type": null,
      "latency_ms": 842.4,
      "token_count": 1180,
      "cost_usd": 0.0124,
      "trace_id": "trace-redacted-id"
    }
  ]
}
```

## 4. Metric catalog

### End-to-end and reliability

- Task success rate: correct final environment outcome.
- Side-effect precision: allowed writes / all writes.
- Duplicate-action rate: duplicated mutations / mutation attempts.
- False-success rate: claims of completion when the outcome is incomplete.
- Recovery rate: successful completion after injected tool/transient failure.
- Loop/termination rate: fraction exceeding step, time, or cost budgets.
- `pass@k = 1 - C(n-c, k) / C(n, k)` when estimating from `n` samples with `c` successes and unbiased sampling assumptions.
- `pass^k`: estimate the probability all `k` independent trials pass; simple estimate is `p^k`, but also report observed all-pass groups when enough runs exist.

### Tool calling

- Tool selection precision/recall/F1.
- Argument schema validity.
- Semantic argument accuracy, exact or field-weighted.
- Required-order compliance.
- Forbidden-call rate.
- Result-utilization correctness.
- Idempotency and retry correctness.
- State transition correctness.

### RAG

- Recall@k: relevant items retrieved / all relevant items.
- Precision@k: relevant retrieved items / k.
- MRR: reciprocal rank of the first relevant item.
- nDCG@k: graded relevance with rank discount.
- Evidence coverage: required evidence units retrieved / all required evidence units.
- Context relevance and distractor rate.
- Claim-level faithfulness: supported material claims / all material claims.
- Citation precision: citations supporting their attached claims / all citations.
- Citation recall: supported claims with citations / claims that require citations.
- Answer completeness, relevance, abstention accuracy, and freshness.

### Multi-agent

- Handoff precision/recall and wrong-recipient rate.
- Delegation coverage: necessary independent subtasks assigned.
- Duplicate-work ratio.
- Conflict rate for shared state or writes.
- Circular-handoff and orphan-task rates.
- Merge loss: correct subagent facts omitted or corrupted in synthesis.
- Team task success versus single-agent baseline.
- Marginal quality per added 1K tokens or dollar.
- Critical-path latency and parallel-efficiency ratio.

### Memory

- Write precision: stored facts that should have been stored / all stored facts.
- Write recall: facts that should persist and were stored / all facts that should persist.
- Retrieval precision/recall.
- Temporal update correctness and stale-value rejection.
- Cross-tenant leakage rate.
- Forget/delete success rate.
- Irrelevant-memory influence rate.
- Compaction survival and long-session reconstruction accuracy.

### Operations

- p50/p95/p99 latency end-to-end and by span kind.
- Tokens and cost per successful task, not only per request.
- Tool/API error, retry, timeout, and rate-limit rates.
- Concurrency saturation and queue delay.
- Human escalation and abandonment rates.
- User outcome and satisfaction, sliced by task and risk.

## 5. Release-gate logic

Apply gates in order:

1. Any critical hard failure -> block.
2. Any forbidden side effect, tenant leak, or false success -> block.
3. Regression suite absolute floor violated -> block.
4. Candidate-baseline delta worse than allowed tolerance with meaningful uncertainty -> block or manual adjudication.
5. Any important slice below its floor even if the global mean passes -> block.
6. Cost or latency SLO violated -> warn or block according to the charter.
7. Judge disagreement or infrastructure failure above threshold -> invalidate the run; do not call it an agent regression.

Example gate configuration:

```json
{
  "critical": {"required_pass_rate": 1.0, "required_pass_power_3": 1.0},
  "regression": {"minimum_pass_rate": 0.97, "max_delta": -0.01},
  "answer_quality": {"minimum": 0.82, "max_delta": -0.02},
  "tool_forbidden_call_rate": {"maximum": 0.0},
  "latency_p95_ms": {"maximum": 5000},
  "cost_per_success_usd": {"maximum": 0.20}
}
```

## 6. Dataset lifecycle

```text
Production trace or requirement
  -> redact and classify
  -> reproduce in hermetic fixture
  -> validate reference solution
  -> add to development set
  -> fix agent and verify
  -> promote stable case to regression
  -> keep blind holdout separate
  -> monitor saturation, drift, and ownership
```

Do not silently rewrite a golden. Record review status, reviewer, change reason, old/new versions, and affected baselines. If the world changes, use temporal expectations or a frozen corpus snapshot.

## 7. Failure taxonomy

Use stable machine-readable reason codes:

```text
EVAL_INVALID_TASK
EVAL_INVALID_GRADER
HARNESS_ENVIRONMENT
HARNESS_DEPENDENCY
AGENT_ROUTING
AGENT_PLANNING
RAG_RETRIEVAL
RAG_GROUNDING
TOOL_SELECTION
TOOL_ARGUMENTS
TOOL_EXECUTION
TOOL_RESULT_USE
MULTI_AGENT_HANDOFF
MULTI_AGENT_COORDINATION
MEMORY_WRITE
MEMORY_RETRIEVAL
MEMORY_ISOLATION
POLICY_AUTHORIZATION
POLICY_INSTRUCTION
ANSWER_CORRECTNESS
ANSWER_COMPLETENESS
ANSWER_UX
PERFORMANCE_TIMEOUT
PERFORMANCE_COST
TERMINATION_LOOP
UNKNOWN
```

## 8. Statistical notes

- Use paired comparisons: same case, fixture, and trial policy for baseline and candidate.
- Stratify by risk and production slice before sampling.
- Report numerator/denominator, not only percentages.
- Use bootstrap intervals for metric deltas when analytical assumptions are weak.
- Use McNemar's test for paired binary outcomes when sample size is adequate.
- Correct for repeated peeking or multiple comparisons in large experiment matrices.
- Do not treat trials sharing a broken environment dependency as independent.
- Distinguish model variance, judge variance, and infrastructure variance.
- Set sample size from the smallest regression worth detecting; do not invent universal counts.

## 9. Choosing thresholds

Do not copy example numbers into a release gate. Derive each threshold in this order:

1. **Hard invariants:** set zero tolerance from product policy or irreversible-loss analysis, such as unauthorized writes, cross-tenant disclosure, duplicate payment, or false success.
2. **Product SLO:** obtain the existing latency, availability, cost, and user-outcome commitments. Missing mandatory SLOs make the release comparison `INVALID_RUN`, not pass.
3. **Baseline:** run the currently approved production configuration on the same cases, fixtures, and trial schedule. Record distribution, slice floors, variance, and infrastructure error rate.
4. **Minimum detectable regression:** have the product and domain owner state the smallest degradation whose user or business loss is unacceptable.
5. **Sample size:** estimate cases/trials needed to detect that delta at the chosen error rates; if the suite is smaller, report uncertainty and require manual adjudication rather than false precision.
6. **Absolute floor plus delta:** gate on both. A candidate cannot pass merely because a weak baseline is worse, and a high aggregate cannot hide a failed critical slice.
7. **Backtest:** apply the proposed gate to historical good releases and known incidents. Adjust only when it misclassifies for a documented reason.
8. **Ownership:** version the threshold, rationale, approver, effective date, and expiry/review date.

For a new system with no baseline, first run manual acceptance and shadow traffic to establish one. Do not label the first arbitrary score as a production-quality threshold.

## 10. Multilingual evaluation

Treat language as a slice and a behavior, not only a translation field.

- Build native cases from real usage for every supported language; translated cases supplement but do not replace them.
- Use qualified native or domain-fluent reviewers for the human oracle slice.
- Pair semantically equivalent cases across languages to test outcome parity while allowing culturally and grammatically appropriate wording.
- Include code-switching, transliteration, locale-specific dates/numbers/currency, typos, formal/informal registers, and mixed-language tool entities.
- Keep tool arguments in their canonical domain representation; separately grade whether localized text was normalized correctly.
- Map citations to source spans in the original document. When the answer translates a claim, judge semantic support rather than string overlap and retain the original evidence span.
- Report task success, retrieval, grounding, tool, handoff, memory, and judge agreement per language. Never hide a weak language behind the global mean.
- Calibrate the judge separately per language. If human agreement is insufficient, use deterministic checks plus human review rather than an unvalidated English-centric judge.
- Test cross-language memory explicitly: write in one language, retrieve or update in another, and reject entity collisions caused by transliteration.

## 11. Fault injection and replay contract

Define failures at observable transaction boundaries. A tool fake or record/replay adapter should accept this portable contract:

```json
{
  "target": "issue_refund",
  "mode": "timeout_after_commit",
  "attempt": 1,
  "match_arguments": {"order_id": "A-100"},
  "result_fixture": null,
  "delay_ms": 0,
  "repeat": 1
}
```

Recommended modes:

```text
success
timeout_before_commit
timeout_after_commit
transient_error_before_commit
transient_error_after_commit
permanent_error
malformed_result
partial_result
stale_result
duplicate_result
out_of_order_result
rate_limited
unavailable
```

The adapter must record an append-only operation ledger containing `operation_id`, idempotency key, canonical arguments hash, attempt, start/end time, commit marker, resulting state version, returned fixture, and injected fault. The agent must not see hidden fault configuration or grader fields.

For a case whose expected outcome is one committed mutation, check three observations:

1. The final source-of-truth state contains one intended mutation.
2. The operation ledger contains at most one committed operation for the idempotency key.
3. Replaying the same request or retry schedule leaves the state version and business result unchanged except for allowed audit records.

Record/replay data must be sanitized, versioned, deterministic, and scoped to the case. Prefer semantic fixtures over raw production payloads. Detect API-schema drift separately so an obsolete recording does not look like an agent regression.

Exercise the recovery path through the normal client. After the destination commits, drop the acknowledgment, observe the status shown to the user, then reconnect. Resolve the original operation under the authorized identity using a receipt lookup or supported same-key replay. The revision may already have advanced because the operation succeeded. Check the receipt belongs to that operation, matches the original arguments, and leads to one durable effect. Include a different operation on the same object as a control. Reusing a key with changed arguments or presenting another actor's receipt must never acknowledge the new request. When reconciliation is unavailable, assert that the visible outcome stays unknown and no fresh mutation is dispatched. A pre-dispatch failure needs its own expectation.

## 12. Turn-level grader controls

For each obligation, write down the turn when it falls due, the source of truth, the evidence the grader may read, and at least one acceptable outcome. For an answer grader, expose the delivered text or cards and earlier user-visible context plus the relevant reference facts. Give a state grader the destination record and operation identity. Inspect tool observations and drafts separately when diagnosing a failure. If the client delivery record is missing, mark delivery unverified. An observed empty reply is evidence of an omission.

Use paired fixtures to check the scorer itself before comparing agents. For example, a scheduling assistant receives two available appointments. Accessibility is documented for one room and unknown for the other.

| Change one condition | Expected grading behavior |
|---|---|
| Keep the facts and correct internal draft fixed. Suppress the confirmed accessible slot in the delivered answer to a request for that option. | The visible-answer criterion fails. Restoring the same fact in a delivered card on that turn can pass. |
| Deliver the required detail only after the user asks again. | The first-turn omission still fails. The recovery turn can pass independently. |
| Change “I prefer a step-free room” to “Only offer a room with confirmed step-free access.” | Allow qualified alternatives for the preference. Require evidence for each offered match under the strict constraint. For both cases an unsupported guarantee fails grounding, and a blanket refusal that hides the known match fails usefulness. |
| Keep both available slots but change which room the tool confirms. | The answer must follow the updated observation. Multiple wordings and valid orders can pass. |

Make the rubric independent of the agent's own intent labels. Confirm which criteria actually feed the verdict by introducing a known failure in each required dimension and observing the gate. For a semantic judge, keep independent human labels and representative disagreements. An uncalibrated score can guide investigation while semantic qualification remains open.

When reviewing stored runs, retain immutable generations and link each new grade to its parent run, artifact digest, case/turn, and evaluator fingerprint (evidence selection, rubric, grader code, judge model/settings). Compare baseline and candidate with the same evaluator and compatible case facts. Missing delivered output cannot be reconstructed from a draft. Report new grading calls/cost separately from the original generation calls/cost. A changed runtime needs its own generation evidence for a current-build behavior claim.

Method references checked 2026-11-22. Anthropic distinguishes observed outcomes from traces. The pinned τ²-bench guide shows how a task selects environment and communication checks for its reward. The fixtures above apply those distinctions to turn-specific product obligations. [Anthropic agent evaluations](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) · [τ²-bench evaluation criteria](https://github.com/sierra-research/tau2-bench/blob/033bf082f48e4a3c6a1256208e93cf2ce9c3bb6f/docs/evaluation.md)
