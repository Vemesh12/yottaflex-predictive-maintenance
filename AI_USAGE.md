# AI Usage Disclosure

AI tools were used heavily in this project. This document states which tools, what they did, how
their output was checked and corrected, and where every prompt is recorded.

## Tools used

| Tool | How it was used |
|---|---|
| **ChatGPT** | Planning at the start: understanding the brief, a 72-hour plan, a first architecture proposal |
| **Claude Code** (Claude Opus 5.5, VS Code extension) | Stack decision, implementation, tests, documentation, debugging |

No other AI tools were used.

## What AI was used for

**ChatGPT** proposed a first plan: a rule-based risk score, the entity list, an evaluation-metric
list and a stack of React + FastAPI + PostgreSQL + DuckDB. Parts of it were adopted (Python for the
data work, rule-based explainable scoring, the metrics). Parts were rejected: PostgreSQL was dropped
so reviewers need no database server, and the web dashboard was dropped because the problem statement
does not ask for one.

**Claude Code wrote nearly all of the code, tests and documentation in this repository**, from my
instructions, in three stages:

| Stage | AI-generated |
|---|---|
| Day 1 | Generator for master data, shift calendar, operating states, telemetry; DuckDB schema and loader; data dictionary; first tests |
| Day 2 | Failures with pre-failure drift, sensor faults, work orders/parts/technicians/status history, the 5 bad-data scenarios, ground truth, validator, JSON/SQL export, tests |
| Day 3 | Feature engineering, explainable risk engine, chronological evaluation, tests, methodology doc |

The decisions and constraints were mine. Claude Code proposed designs; I chose:
- the stack (Python for the data work instead of Node, after asking for the reasoning),
- no frontend,
- an audit of the existing code before each new stage,
- the rules that no future data or ground truth may be used as features, that results must not be
  hardcoded, that generation must be deterministic, and that existing tests must keep passing,
- the format of the prompt history.

## How the generated code was reviewed, tested and corrected

**Automated checks run on every stage:**
- 71 pytest tests (data volumes, ID formats, every primary and foreign key, state-history
  continuity, failure timelines, sensor-fault isolation, cost reconciliation, edge-case detection,
  export round-trips, no-leakage checks, metric calculations).
- `python -m pipeline validate`: 83 rule checks. They must all pass on the clean data, and all
  118 injected bad records must be found with no false positives.
- Loading into DuckDB with every PK/FK/CHECK constraint enabled.
- Reproducibility: the full dataset generated twice with the same seed gives identical SHA-256
  checksums for every output file.

**Checks designed to catch AI output that only *looks* right:**
- A test corrupts a copy of the clean data in ways the ground truth does not know about. The
  validator must fail, which proves its results are computed rather than hardcoded.
- A test multiplies all telemetry after day 15 by 10, deletes future records and deletes ground
  truth. The risk features for earlier days must not change, which proves there is no future leakage.
- A test deletes all failures after the validation period. The chosen alert level must not change.

**Problems found during development and corrected** (found by running the code and tests during
the Claude Code sessions, before each stage was committed):

| Problem | Correction |
|---|---|
| Failure count (116) too close to the 100 minimum | Hazard rates re-tuned; checked across 8 seeds (144–185) |
| 23% of preventive jobs cancelled after repairs (unrealistic) | Cancellation window shortened from 7 to 3 days (~10%) |
| Validator: invalid SQL (nested window functions, `rowid` on file views) | Queries rewritten |
| Validator flagged stopped machines as "stuck" sensors | Restricted to readings taken while RUNNING |
| Validator then missed a sensor dropout that happened on a weekend | Dropout check uses all readings |
| Risk engine v1: temperature-only failures could never reach an alert (overheating 0/10 detected) | Weights rebalanced so each sensor group can earn the same points (overheating 8/10, F1 0.48 → 0.56) |
| Stuck-sensor detection caught only 12/24 cases | Rule changed to "6 identical readings in a row" (20/24) |
| A test was too strict (matched a comment in `seed.sql`) | Test changed to check for real ground-truth content |

Results that were *not* tuned to look better are reported as they are: spike detection 5/8, bias
faults undetectable from one sensor, electrical faults 0/8 caught by the risk engine.

## My own review

Claude Code wrote most of the code. My part was to direct the work, review it, and check that the
results made sense.

**What I reviewed**
- The overall flow: generate → validate → score → evaluate, and how each stage feeds the next.
- The generated data: the master tables, failure events, work orders, the bad-data scenarios and
  the ground-truth file.
- The validation summary, to confirm that the clean data passes and every injected problem is found.
- The risk scores and the evaluation results, to understand where the engine works well (bearing
  wear, pressure loss) and where it does not (electrical faults, sensor bias).

**How I tested it**
- I ran the pipeline and the test suite at each stage.
- When tests or validation found a problem, I had it diagnosed and fixed with Claude Code, then
  re-ran the checks before moving on.

**What I learned**
This project taught me how to build a complete data-generation and predictive-maintenance workflow:
creating realistic industrial data, validating it, and evaluating failure risk. It also showed me
why reproducibility, data quality, avoiding data leakage and documenting limitations honestly
matter.

## Where the prompts are

Every prompt sent to both tools is in [prompts/prompt-history.md](prompts/prompt-history.md), in
order. The prompts are edited for spelling and grammar only; none were removed or added. Text pasted
from the confidential assessment brief (the problem statement and recruitment email) is replaced by
a marker, because the assessment terms forbid publishing it. AI responses are not included.

## Responsibility

I am responsible for the final implementation in this repository. I directed the work, decided what
to keep and what to change, and I can explain the design, the code, the assumptions and the
limitations.
