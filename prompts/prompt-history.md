# Prompt History

Every prompt I sent to an AI tool for this project, in order. AI responses are not included, as
the FAQ allows.

**Editing note:** prompts are edited for spelling, grammar and formatting only. No prompts are
removed or added, and the content and intent of each one are unchanged. Where a prompt contained
the confidential assessment brief (problem statement, recruitment email, guidelines), the pasted
text is replaced by a marker such as `[pasted problem statement omitted]`, because the assessment
terms forbid publishing it.

## Summary

| # | Date | Tool | Phase | Topic |
|---|---|---|---|---|
| 1 | 2026-10-30 | ChatGPT | Planning | How to approach the challenge |
| 2 | 2026-10-30 | ChatGPT | Planning | Architecture for the problem statement |
| 3 | 2026-10-30 | Claude Code | Stack decision | Python vs Node; JavaScript vs TypeScript |
| 4 | 2026-10-30 | Claude Code | Stack decision | Replacing PostgreSQL |
| 5 | 2026-10-30 | Claude Code | Planning | Problem breakdown and 3-day plan |
| 6 | 2026-10-30 | Claude Code | Day 1 build | Implement Day 1 and document it |
| 7 | 2026-10-30 | Claude Code | Scope | Frontend needed? Prompt-history format |
| 8 | 2026-10-30 | Claude Code | Process | Prompt-history format |
| 9 | 2026-10-30 | Claude Code | Day 2 build | Audit, plan and implement Day 2 |

---

## Tool 1: ChatGPT (planning)

### 1. How to approach the challenge

```text
[pasted recruitment email, submission guidelines and FAQ omitted]

Based on this, what should I do now?
```

### 2. Architecture for the problem statement

```text
[pasted problem statement omitted]
```

---

## Tool 2: Claude Code (Claude Opus 5.5, VS Code extension)

### 3. Python vs Node; JavaScript vs TypeScript

```text
Review the PDF in the root folder and create a Markdown file from it.

Then explain: why Python and not Node? I want to use React with JavaScript. Is that fine, or
should I stay with TypeScript?
```

### 4. Replacing PostgreSQL

```text
So we are not using PostgreSQL now, right? What do we use instead, and how do I use it?
I don't have it installed on my system.
```

### 5. Problem breakdown and 3-day plan

```text
[pasted problem statement omitted]

This is the problem statement. Save it as a separate Markdown file and tell me the plan.
```

### 6. Implement Day 1 and document it

```text
Implement Day 1 now, and tell me whether it is complete.

Also explain clearly what you built: document everything we build in a separate Markdown file.
This file is for me only, so add it to .gitignore.
```

### 7. Frontend needed? Prompt-history format

```text
OneDrive sync is already paused, so I think there is no issue there.

We don't need the frontend, right? Only Python with some data analysis?

Also, I want the prompt history to look good, because they check the prompts I gave you.
Restructure the prompts: remove the silly ones and keep only prompts about architecture,
explanations of the logic, and why things are needed.
```

### 8. Prompt-history format

```text
No, change the prompts I gave you. Restructure the prompts themselves in the Markdown file,
not the explanations.
```

### 9. Audit, plan and implement Day 2

```text
I have completed Day 1 of my industrial predictive maintenance data-generation project. Now I
want to start Day 2.

Before writing or changing any code, inspect my existing project thoroughly. Read the folder
structure, README, documentation, generators, database schema, models, validation logic,
configuration, and tests. Understand how the current system works and how its components connect.

Do not assume anything about the implementation. Verify it from the actual code.

After understanding the project:
1. Summarize the existing architecture and data flow.
2. Identify what is already implemented and what Day 2 still needs.
3. Suggest the best implementation order based on my existing architecture.

Day 2 requirements:
- Generate 100–200 realistic machine failure events with gradual warning signs in telemetry.
- Generate maintenance work orders, technicians, parts, downtime, and costs with proper
  relationships and lifecycle history.
- Simulate sensor faults separately from actual machine failures.
- Add the five required deliberate bad-data scenarios: unknown sensor, impossible sensor value,
  failure before symptom, maintenance end before start, and missing readings incorrectly
  represented as zero.
- Keep invalid scenarios separate from clean baseline data.
- Generate a separate ground-truth dataset. Never expose ground-truth labels as model input
  features.
- Implement validation to detect the expected anomalies and report unexpected data-integrity
  issues.
- Export the required datasets in CSV, JSON, and SQL formats.
- Add automated tests and update the documentation.

Important:
- Preserve the existing Day 1 implementation and all passing tests.
- Follow the current project structure and coding conventions.
- Reuse existing utilities and models instead of unnecessarily rebuilding them.
- Keep generation deterministic using the existing seed.
- Do not hardcode validation results just to make tests pass.
- Do not start Day 3 or build a dashboard yet.

Work incrementally. First show me your repository audit and implementation plan. After that,
implement each part, run the tests, fix issues, and explain the changes.

Also write detailed notes in the build notes about what you wrote, so that I can understand
everything very clearly when I read it.
```
