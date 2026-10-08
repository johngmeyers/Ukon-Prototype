# Decision log

Short records of the main design decisions: the context, the decision, and what it costs.

## 1. Comparison is deterministic code, not the LLM

**Context.** Deciding that an application answer is contradicted is the high-stakes step. A wrong "supported" can leave a business uncovered at claim time, and the agency carries the errors-and-omissions exposure.

**Decision.** The LLM only turns text into canonical fields. A plain-function rule set in `compare.py` makes every judgment, with a fixed order of checks. The decision table in `tests/test_compare.py` was written and reviewed before the implementation.

**Consequences.** Every finding has a reason a person can read and check. A rule change shows up as a test diff, not a prompt tweak. Evals can tell a mapping miss from a rule miss. The rules can't cover a nuance nobody wrote down; those cases fall to needs review.

## 2. Parsers for structured exports; the LLM only for free text

**Context.** M365 MFA reports, EDR inventories and patch exports are already structured. MSP notes and backup logs are not.

**Decision.** CSV and JSON exports go through deterministic parsers that report facts, such as "EDR active on 47 of 50 devices (94%)". The LLM reads only free text and application answers, using the same validated, logged call pattern.

**Consequences.** Lower cost and no model error on the structured data, and parsers fail loudly on malformed files. Each new export format needs a parser.

## 3. Review threshold at confidence 0.8

**Context.** The mapper and notes reader return a confidence for each field. Some answers are genuinely unclear ("MFA on most systems").

**Decision.** A claim or LLM-read evidence below 0.8 goes to needs review, whatever the evidence says. The value lives in one config dict (`config.THRESHOLDS`).

**Consequences.** Simple and auditable. The confidence is self-reported by the model and uncalibrated, so 0.8 is a starting point. The eval harness reports review rate next to recall, so the threshold can be tuned against labeled data rather than guessed.

## 4. Uncertain findings are never auto-resolved

**Context.** Missing a real gap is the costly error. A false alarm only wastes reviewer time.

**Decision.** Low confidence, a missing or null claim, and evidence sources that disagree all produce `needs_review`. The system never picks a side. The report lists needs review right after contradictions.

**Consequences.** Some correct answers reach a human (a 3% review rate on the eval set with v2). The evals report "gaps caught" (contradicted or needs review) alongside strict contradiction recall, so routing a gap to a human is visible as safe but not counted as a full catch.

## 5. Synthetic data only

**Context.** Real applications and MSP exports contain customer and carrier data.

**Decision.** Every carrier question set, application and evidence file is written for this prototype, and domains use `.example`. `CLAUDE.md` forbids adding real data.

**Consequences.** Safe to share and demo. Accuracy numbers say nothing about real submissions until the eval set includes anonymized real ones.

## 6. Schema-constrained output instead of forced tool use

**Context.** The plan called for forced tool use at temperature 0. Claude Opus 5.5 and Sonnet 5.5 reject both a forced `tool_choice` and `temperature`.

**Decision.** Use structured outputs: a JSON schema generated from the Pydantic model, which constrains the reply. Validate every reply with Pydantic, retry once with the validation error, then fail loudly. Log every attempt. Server-side refusal fallback is on, and the log records which model actually answered.

**Consequences.** One schema still drives the request, validation and tests. Numeric bounds such as confidence 0–1 aren't enforced by the API's schema, so Pydantic enforces them and the retry handles violations. Without temperature control, consistency is measured instead: status stability across eval runs was 99% on v1 and 100% on v2.

## 7. Sonnet 5.5 is the default model, chosen by eval

**Context.** The prototype started on Claude Opus 5.5 at $0.052 per application. The LLM's job here is narrow (extract fields from short text), so a cheaper model might do as well.

**Decision.** Run the same 16 scenarios and v2 prompts on Opus 5.5, Sonnet 5.5 and Haiku 5.5, 2 runs each, and pick from the data. Sonnet 5.5 had 100% recall, precision and status accuracy in both runs, at $0.026 per application and a 9.3s median, against Opus's 99.4%, $0.052 and 16.1s. Haiku 5.5 also had 100% recall at $0.0016, but it read a vague answer ("We back up to the cloud") as a confident "no" in both runs instead of sending it to review.

**Consequences.** Half the cost and faster demos, with no measured quality loss. `--model` switches per run, and eval result names always include the model. Haiku's overconfidence on vague wording is the case to fix (for example with quote verification) before trading accuracy for its 30× lower cost.
