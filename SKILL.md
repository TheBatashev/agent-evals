---
name: agent-evals
description: Design, implement, review, and operate production-grade evaluations for LLM applications and AI agents. Use for Agent Evals, LLM Evals, RAG evaluation, tool/function-calling tests, MCP tests, multi-agent and handoff evaluation, memory tests, golden datasets, LLM-as-judge calibration, AI regression testing, CI/CD quality gates, model or prompt comparisons, agent benchmarks, AI QA, tracing, and production observability.
---

# Agent Evals

Build evidence that an AI system completes real tasks reliably, not merely that its final text looks plausible. Treat the model, prompt, tools, orchestration, state, data, and environment as one versioned system under test.

## Operating contract

For every non-trivial request:

1. Trace the affected behavior from the entrypoint to the evidence needed for the decision. If reviewing a supplied evidence packet, state which claims it supports and which require another observation.
2. State a short implementation plan before modifying files.
3. Define product success and unacceptable failure before choosing metrics or a vendor.
4. Match evidence to the claim. Check durable effects in the destination system, user-facing quality in what was delivered on the relevant turn, and ordering in observable events when order is part of the contract. A task can require all three.
5. Isolate external effects with a hermetic fixture, sandbox, record/replay layer, fake clock, seeded data, and idempotent cleanup. Never let offline evals mutate production.
6. Version the system configuration, dataset, environment fixture, graders, judge model/prompt, and run results together.
7. Run repeated trials for nondeterministic behavior and report uncertainty, not only a mean score.
8. Convert every confirmed production failure into a regression case after redaction and root-cause classification.
9. Calibrate model graders against human-labeled examples and revalidate them when the judge, rubric, domain, or output distribution changes.
10. Match the work to the decision. For an incident, start with one reproducible failure and a contrasting valid case. For implementation, run the affected checks through the normal entrypoint. For a release, identify the required gates and evidence for the candidate build. Keep paid trials and external effects within the user's authorization.

## Start with the Outcome-first Eval Pyramid

Use the smallest set of layers that can locate failures without overfitting the implementation path.

| Layer | Primary question | Preferred grader | Gate role |
|---|---|---|---|
| Outcome/environment | Did the requested state change actually occur, and only once? | Database/API/file/browser assertions, unit tests | Hard gate |
| Policy/safety | Were permissions, constraints, and irreversible actions respected? | Deterministic policy assertions plus adversarial cases | Hard gate |
| Trajectory | Did the workflow select a valid, efficient route? | Required/forbidden step assertions; calibrated judge for flexible paths | Diagnostic or hard for invariants |
| Component | Did routing, retrieval, tool use, handoff, and memory work? | Exact/schema/set/IR metrics | Fast PR gate |
| Response | Is the answer correct, grounded, complete, and usable? | Reference checks plus calibrated rubric | Quality gate |
| Operations | Is reliability acceptable at production cost and latency? | Repeated trials, percentiles, error taxonomy | SLO gate |

Do not require an exact trajectory when several valid routes exist. Require exact ordering only for true invariants such as authorization before mutation.

## Execute the workflow

### 1. Map the system and risks

Produce an eval inventory containing:

- user jobs and business outcomes;
- nondeterministic boundaries: model calls, routers, tools, retrieval, handoffs, memory, simulators;
- irreversible or high-impact actions;
- expected state transitions and sources of truth;
- supported languages, modalities, tenants, roles, and long-context behavior;
- latency, token, cost, concurrency, retry, and rate-limit constraints;
- known incidents, support tickets, thumbs-down traces, and manual release checks.

Assign each failure a severity and detection layer. Require zero tolerance for critical policy violations, unauthorized writes, secret/PII exposure, duplicate side effects, and false success claims.

### 2. Write an eval charter

Before code, define:

- decision the eval will enable;
- target population and production distribution;
- unit under test: component, turn, session, agent, or system;
- success, partial success, and unacceptable failure;
- baseline and candidate configuration;
- metrics and per-slice thresholds;
- number of trials and statistical comparison;
- expected artifacts and owner;
- release policy: block, warn, or observe.

Keep capability and regression suites separate:

- `capability`: hard unsolved tasks used for hill-climbing; expected to have headroom;
- `regression`: known supported behavior; target nearly 100% on deterministic critical cases;
- `safety`: adversarial misuse and boundary tests; hard gates;
- `production`: sampled and redacted live traces for drift monitoring;
- `judge-calibration`: human labels used only to validate graders;
- `benchmark`: public comparisons, never the sole release gate.

### 3. Build the dataset

Use stable case IDs and JSONL or typed fixtures. Each case must include input, isolated environment state, expected outcome or rubric, risk, slice tags, provenance, owner, and dataset version. Read [references/eval-design.md](references/eval-design.md) for the canonical schema and [references/templates.md](references/templates.md) for examples.

Dataset rules:

- Group cases by failure mechanism. Preserve the redacted incident, vary wording and prior state independently, and include a neighbor where the opposite behavior is correct. Keep siblings together when splitting off a blind holdout.
- Include positive, negative, boundary, ambiguous, multilingual, long-context, malformed, adversarial, timeout, retry, partial-failure, and recovery cases.
- Balance trigger/non-trigger pairs: call versus do not call, retrieve versus answer directly, handoff versus stay, remember versus forget.
- Keep development, regression, calibration, and blind holdout partitions separate.
- Deduplicate semantic variants across splits; keep benchmark answers and hidden grader data unavailable to the agent.
- Validate every task with a known reference solution or executable proof that the task and harness are solvable.
- Preserve frozen historical cases; update mutable knowledge with an `as_of` time and versioned corpus snapshot.
- Redact production data and retain provenance without secrets or unnecessary personal data.

Run `python scripts/validate_eval_dataset.py <dataset.jsonl>` after authoring or changing a dataset.

The bundled command checks structure. Also resolve expected IDs, facts and permitted alternatives against the fixture or corpus snapshot used for that run. An obsolete expectation invalidates the affected comparison. Preserve the old case and record the corrected version.

### 4. Choose graders by criterion

Use a grader Strategy per atomic criterion:

1. Exact programmatic check: schema, value, set membership, database state, citation span, tool name/arguments, policy invariant.
2. Executable check: unit/integration/browser test, compiler, SQL execution, sandboxed task completion.
3. Retrieval metric: recall@k, precision@k, MRR, nDCG, evidence coverage, freshness, ACL correctness.
4. Model grader: subjective quality, semantic equivalence, flexible trajectory, source quality, or completeness.
5. Human review: ambiguous high-impact outputs, grader calibration, new failure discovery, and release adjudication.

Split broad ideas such as “helpfulness” into observable criteria. Prefer binary or pairwise decisions with explicit anchors over unanchored 1-10 scores. Return a structured label, reason code, evidence span, confidence, and grader version.

Never use one opaque composite score as the only gate. Keep dimensions separate, then define explicit hard failures and weighted product metrics.

For a conversational task, specify which facts the agent had and what the user needed by each turn. Check factual support, permission, and useful progress independently. Give the answer grader only the delivered messages/cards up to that turn and the minimum authoritative facts needed to grade them. Keep internal plans and later turns in the diagnostic trace. Test this evidence boundary with the [worked grader controls](references/eval-design.md#12-turn-level-grader-controls).

### 5. Calibrate LLM-as-judge

Create an oracle slice with representative pass, fail, and borderline outputs labeled independently by at least two qualified humans. Measure agreement using confusion matrices and a task-appropriate statistic such as accuracy/F1 for binary labels, Cohen/Fleiss kappa for categorical labels, or rank correlation for rankings.

Test the judge for:

- position bias by swapping pair order;
- verbosity and style bias with meaning-preserving perturbations;
- self/preference bias across model families;
- prompt injection inside candidate output or retrieved evidence;
- missing-evidence behavior and abstention;
- stability across repeated runs;
- false-positive rate on critical failures.

Pin the judge model and rubric version. Fail the grader validation if agreement or critical-class recall falls below the charter threshold. Never expose private chain-of-thought; grade observable traces, actions, evidence, outputs, and environment state.

### 6. Measure nondeterministic reliability

Run multiple independent trials on important cases. Report:

- `pass_rate`: successful trials / all trials;
- `pass@k`: probability at least one of k attempts succeeds; use only when retries are a real product feature;
- `pass^k`: probability all k attempts succeed; use for reliability and consistency;
- per-case variance and worst slice;
- bootstrap confidence interval or paired resampling interval for candidate-baseline deltas;
- paired results on identical cases and environment snapshots.

Do not hide instability behind averages. For critical workflows, gate on per-case `pass^k`, not aggregate mean alone.

### 7. Add domain-specific evals

#### RAG

Evaluate retrieval and generation separately, then end-to-end:

- corpus ingestion completeness, parsing, chunk metadata, freshness, deletions, tenant/ACL isolation;
- recall@k, precision@k, MRR/nDCG, multi-hop evidence coverage, distractor robustness, empty-result behavior;
- faithfulness/groundedness at claim level, citation correctness, answer relevance, completeness, and calibrated abstention;
- sensitivity to chunking, top-k, reranker, query rewriting, language, document version, and context order;
- latency and cost for embedding, retrieval, reranking, and generation independently.

The answer must not receive a passing groundedness grade merely because retrieved context contains the fact; map each material claim to supporting evidence.

#### Tool and function calling

Test tool selection, non-selection, argument schema, semantic argument correctness, authorization, ordering invariants, idempotency, retries, timeout handling, partial failure, malformed output, result interpretation, and final outcome. Test similar tool names and poisoned tool descriptions. Verify state after execution; a syntactically correct call is not task success.

For reads inside a decision loop, vary only the tool observation while holding the request fixed. Check whether the next decision uses the returned facts and whether a failed lookup still permits useful partial progress within the remaining budget. For writes, test a lost acknowledgment after commit through every supported write path using the [fault and replay contract](references/eval-design.md#11-fault-injection-and-replay-contract).

#### Multi-agent systems

Always compare against a single-agent baseline with the same task and comparable budget. Evaluate router/handoff precision and recall, delegation quality, duplicated work, conflicting writes, circular handoffs, message loss, shared-state consistency, stop conditions, merge/synthesis quality, recovery when one agent fails, total tokens, wall time, and marginal quality per added cost. Grade team outcome first; use agent-level traces for attribution.

#### Memory

Test write selection, value accuracy, provenance, retrieval precision/recall, temporal updates, conflict resolution, cross-session persistence, cross-user/tenant isolation, deletion/forgetting, stale-memory rejection, irrelevant-memory non-use, compaction survival, and long-session state reconstruction. Use canary facts and deterministic state inspection; do not rely only on the agent claiming it remembered.

Exercise the context boundary with a growing conversation and realistic tool payloads together. Carry a confirmed constraint and a declined suggestion across compaction, then change the task. Inspect which facts should survive, expire, or be superseded and check their effect on the next visible action. When users request alternatives, distinguish candidates retrieved, shown, and selected.

### 8. Automate gates and observability

Use a tiered CI policy:

- per commit: deterministic unit/component cases and a small smoke subset;
- pull request: regression, safety, judge smoke, and paired candidate-baseline comparison;
- merge/nightly: full suite with repeated trials and slice report;
- model/prompt/tool/corpus change: targeted plus full affected suites;
- production: asynchronous sampled scoring, SLO alerts, drift slices, and human review queue.

Block a release when a critical case fails, a hard policy invariant breaks, a regression slice exceeds its allowed delta, or latency/cost SLOs are violated. Use absolute floors plus maximum allowed delta; do not gate only on “better than baseline.” Quarantine only proven infrastructure flakes with an owner and expiry.

Derive thresholds from hard invariants, product SLOs, an approved paired baseline, the smallest unacceptable regression, and sufficient sample size. Never copy universal-looking thresholds from an example. Treat a release comparison with missing mandatory SLOs or no valid baseline as `INVALID_RUN`. Follow the threshold, multilingual, and fault/replay protocols in [references/eval-design.md](references/eval-design.md).

Instrument trace and span IDs, session/case/trial IDs, agent and tool names, sanitized inputs/outputs, state transitions, retrieval document IDs/scores, model/prompt/tool/corpus versions, token counts, cost, latency, retries, errors, grader outputs, and deployment metadata. Prefer OpenTelemetry/OpenInference-compatible traces when possible.

### 9. Analyze failures before tuning

Classify every failure as one of:

- invalid task or grader;
- harness/environment/infrastructure;
- routing/planning;
- retrieval/context;
- tool selection/arguments/execution/result use;
- handoff/coordination;
- memory/state;
- policy/authorization;
- answer correctness/grounding/UX;
- timeout/cost/loop/termination;
- unknown.

Read representative transcripts from passes and failures. Fix invalid evals before optimizing the agent. Preserve valid alternative solutions instead of forcing one reference path.

## Quality criteria for the eval system

An eval suite is release-ready only when:

- its tasks match product requirements and production slices;
- reference solutions prove task and harness solvability;
- critical outcomes use deterministic or executable verification;
- graders are versioned, explainable, and human-calibrated where applicable;
- repeated trials expose variability and uncertainty;
- baseline comparisons are paired and reproducible;
- failure taxonomy points to an actionable subsystem;
- test environments prevent production writes and cross-case contamination;
- costs, latency, tokens, retries, and error rates are measured;
- CI thresholds have owners and documented override rules;
- production traces feed new redacted regression cases;
- saturated capability suites are refreshed while stable cases graduate to regression.

## Anti-patterns

- Vibe checking or a few hand-picked demos.
- Public benchmark score as proof of product quality.
- Exact-string grading for open-ended valid answers.
- LLM judge without human calibration or adversarial meta-evals.
- One trial per case for a stochastic agent.
- Only happy paths or only “tool should be called” cases.
- Grading the final message while ignoring the real environment state.
- Enforcing one golden trajectory when many routes are valid.
- Mixing mutable production examples into a supposedly frozen regression baseline.
- Tuning prompts and graders on the blind holdout.
- Averaging away catastrophic slice failures.
- Comparing multi-agent quality without equal-budget and single-agent baselines.
- Logging secrets, raw private data, or hidden judge answers into agent-visible traces.
- Treating a 100% capability suite as proof of further progress.

## Tool selection

Keep the internal dataset and scorer interfaces portable. Choose tools after the eval contract exists:

| Need | Strong default |
|---|---|
| Python-first pytest-style local/CI metrics | DeepEval or custom pytest |
| LangChain/LangGraph traces, datasets, trajectory evals | LangSmith plus OpenEvals |
| Vendor-neutral experiments, scoring, production feedback | Braintrust |
| Local YAML model/prompt matrices and security red teaming | Promptfoo |
| RAG research and ready-made retrieval/generation metrics | Ragas, supplemented by deterministic IR metrics |
| Open-source/self-hosted observability and experiments | Phoenix/OpenInference or MLflow GenAI |
| OpenAI Agents SDK trace debugging | OpenAI trace grading; avoid new hard dependency on the retiring legacy Evals platform |
| Maximum portability | Typed JSONL + pytest + OpenTelemetry + provider adapters |

Never install a framework merely to satisfy this matrix. Inspect the existing stack and obtain permission before adding dependencies.

## Required deliverables

For implementation, leave reproducible cases, the checks that decide them, the invocation, and the observed results. Reuse the project's harness. Add a model judge, CI gate or live comparison when the decision calls for it. A design or review request can finish with findings and evidence gaps.

For a release decision, map each required claim to its source/configuration fingerprint, run mode, cases × trials, result, and artifact. Separate fixture checks, fresh model generations, regrades of saved output, human review, browser/device runs and operator acceptance as applicable. Mark missing evidence as untested and show which decision it prevents. A green objective smoke alone leaves semantic quality unmeasured. See the [report template](references/templates.md#8-result-report).

For a client pilot, define who accepts the result, the destination or rubric, and the eligible workload. Compare with the current workflow on comparable cases. Count accepted unique tasks over all eligible arrivals, including pre-run losses. Track handoffs, human corrections and retries separately. Divide total operating and review cost for that cohort by accepted tasks. With zero accepted tasks report spend and zero accepted; the unit cost is undefined.

Use [references/templates.md](references/templates.md) for ready-to-fill templates, [references/eval-design.md](references/eval-design.md) for schemas and formulas, and [references/research-2025-2026.md](references/research-2025-2026.md) when current source rationale or tool comparison is needed.
