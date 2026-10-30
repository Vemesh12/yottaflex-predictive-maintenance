# AI Prompt History

This document records the prompts used during the development of the Industrial Predictive Maintenance project, in chronological order.

It covers project planning, architecture decisions, implementation, testing, documentation, and final submission preparation.

AI responses are not included, as permitted by the assessment FAQ.

> **Editing and confidentiality note:** The original prompts have been reorganized and refined for clarity, grammar, and readability while preserving their original purpose and requirements. No development phase has intentionally been omitted. Any confidential assessment material, including the original problem statement, recruitment email, and assessment guidelines, has been replaced with an appropriate placeholder. The original confidential content is not reproduced in this document.

## 1. Prompt Summary

| # | Date | AI Tool | Development Phase | Topic |
|---|---|---|---|---|
| 1 | 2026-10-30 | ChatGPT | Planning | Understanding the challenge and next steps |
| 2 | 2026-10-30 | ChatGPT | Architecture | Designing the solution architecture |
| 3 | 2026-10-30 | Claude Code | Technology Selection | Python vs Node.js and JavaScript vs TypeScript |
| 4 | 2026-10-30 | Claude Code | Technology Selection | Choosing a database alternative to PostgreSQL |
| 5 | 2026-10-30 | Claude Code | Planning | Breaking down requirements and creating a development plan |
| 6 | 2026-10-30 | Claude Code | Day 1 | Implementing the initial data-generation system |
| 7 | 2026-10-30 | Claude Code | Scope | Confirming frontend requirements and prompt documentation |
| 8 | 2026-10-30 | Claude Code | Documentation | Restructuring the prompt history |
| 9 | 2026-10-30 | Claude Code | Day 2 | Implementing failures, maintenance, anomalies, and validation |
| 10 | 2026-10-30 | Claude Code | Day 3 | Implementing the predictive maintenance risk engine |
| 11 | 2026-10-30 | Claude Code | Submission | AI usage disclosure and limitations review |
| 12 | 2026-10-30 | Claude Code | Documentation | Consolidating project limitations |
| 13 | 2026-10-30 | Claude Code | Submission | Reviewing the personal AI usage statement |

---

# 2. ChatGPT – Project Planning

## Prompt 1: Understanding the Challenge and Next Steps

**Objective:** Understand the assessment requirements and determine the appropriate approach before starting implementation.

```text
[pasted recruitment email, assessment guidelines, and FAQ omitted]

Review the assessment requirements and explain what is expected from me.

Break down the challenge into manageable tasks, identify the important requirements, and suggest how I should approach the implementation within the available time.

Explain what I should do first and what I should prioritize to complete the assessment successfully.
```

## Prompt 2: Designing the Solution Architecture

**Objective:** Understand the technical requirements and identify a suitable architecture for the project.

```text
[pasted confidential problem statement omitted]

Analyze the requirements and propose a suitable technical architecture for this project.

Explain the main components, data flow, relationships between entities, technology choices, and implementation approach.

Break the architecture into clear modules so that I can understand how the complete system should work before implementation.
```

---

# 3. Claude Code – Technology Selection and Planning

**Tool:** Claude Code (Claude Opus 5.5, VS Code extension)

## Prompt 3: Technology Selection – Python vs Node.js

**Objective:** Evaluate the backend language and frontend technology choices.

```text
Review the assessment PDF in the project root and convert its contents into a separate Markdown document for reference.

Based on the requirements, explain why Python is a suitable choice over Node.js for this project.

I am also considering React with JavaScript for the frontend. Is that a reasonable choice, or would TypeScript be more appropriate?

Compare the options based on the actual project requirements and recommend a practical technology stack.
```

## Prompt 4: Choosing a Database Alternative

**Objective:** Understand the selected database and how to work with it locally.

```text
Are we still planning to use PostgreSQL, or have we selected a different database?

Explain which database we should use, why it is suitable for this project, and how I can work with it locally.

I do not currently have the selected database installed, so include the installation or setup steps if required.
```

## Prompt 5: Requirements Breakdown and Three-Day Development Plan

**Objective:** Convert the assessment requirements into an implementation plan.

```text
[pasted confidential problem statement omitted]

Save the assessment problem statement as a separate Markdown file for local reference.

Analyze the complete requirements and break the project into manageable development phases.

Create a practical three-day implementation plan covering:

1. Initial architecture and master data generation.
2. Transaction data, failure simulation, maintenance records, anomalies, and validation.
3. Feature engineering, predictive maintenance risk scoring, and evaluation.

For each day, explain the expected deliverables, dependencies, and important validation steps.

Prioritize the mandatory requirements and distinguish them from optional improvements.
```

---

# 4. Claude Code – Day 1 Implementation

## Prompt 6: Implementing the Initial Data Generation System

**Objective:** Build the foundation of the project and document the implementation.

```text
Implement Day 1 of the industrial predictive maintenance project based on the agreed architecture and requirements.

Start by reviewing the existing project structure and then build the initial data-generation system.

Implement the required master data, entity relationships, identifiers, telemetry generation, and basic validation.

Make sure the generated data is realistic, consistent, and reproducible using a fixed random seed.

After implementation:

1. Run the available tests.
2. Verify the generated datasets and relationships.
3. Confirm that the generation process is reproducible.
4. Explain what has been implemented and whether Day 1 is complete.

Also maintain a separate BUILD_NOTES.md file explaining the implementation, design decisions, and logic in simple language. This document is for my personal reference and should be included in .gitignore.
```

---

# 5. Claude Code – Scope and Documentation

## Prompt 7: Confirming Frontend Requirements and Prompt Documentation

**Objective:** Confirm the project scope and establish a proper prompt-history structure.

```text
OneDrive synchronization is already paused, so there should not be an issue with project files being synchronized.

Based on the assessment requirements, do we actually need a frontend application, or is a Python-based data-generation and analysis solution sufficient?

I also need to maintain a proper AI prompt history because the assessment requires documenting the prompts used during development.

Suggest a clean Markdown structure that organizes the prompts chronologically by development phase.

The prompt history should focus on the actual project work, including architecture decisions, implementation instructions, technical explanations, and important development decisions.
```

## Prompt 8: Restructuring the Actual Prompts

**Objective:** Improve the prompt-history document by organizing and refining the prompts themselves.

```text
I do not want a document containing only summaries or explanations of the prompts.

Restructure the actual prompts I provided and organize them properly in the Markdown file.

Keep them in chronological order, improve their formatting and readability, and organize them under appropriate development phases.

Preserve the original purpose and technical requirements of each prompt.
```

---

# 6. Claude Code – Day 2 Implementation

## Prompt 9: Repository Audit and Day 2 Implementation

**Objective:** Understand the completed Day 1 implementation and extend it with failure simulation, maintenance records, sensor faults, anomalies, and validation.

```text
Day 1 of the industrial predictive maintenance project is complete.

Before implementing Day 2, inspect the existing repository thoroughly. Review the folder structure, documentation, generators, database schema, models, validation logic, configuration, and tests.

Understand how the current implementation works and how its components connect.

First:

1. Summarize the existing architecture and data flow.
2. Identify what is already implemented.
3. Identify the remaining Day 2 requirements.
4. Suggest an implementation order based on the existing architecture.

Day 2 requirements:

- Generate 100–200 realistic machine failure events with gradual warning signs in telemetry.
- Generate maintenance work orders, technicians, parts, downtime, costs, and lifecycle history.
- Simulate sensor faults separately from actual machine failures.
- Implement the five required bad-data scenarios: unknown sensor, impossible sensor value, failure before symptom, maintenance end before start, and missing readings incorrectly represented as zero.
- Keep invalid scenarios separate from clean baseline data.
- Generate a separate ground-truth dataset without exposing its labels as model input features.
- Implement validation to detect the expected anomalies and unexpected data-integrity issues.
- Export datasets in CSV, JSON, and SQL formats.
- Add automated tests and update the documentation.

Important constraints:

- Preserve the existing Day 1 implementation and passing tests.
- Follow the existing project structure and coding conventions.
- Reuse existing utilities and models instead of unnecessarily rebuilding them.
- Maintain deterministic generation using the existing seed.
- Do not hardcode validation results just to make tests pass.
- Do not start Day 3 or build a dashboard yet.

Work incrementally. First provide the repository audit and implementation plan. Then implement the required components, run the tests, fix any issues, and explain the changes.

Also update BUILD_NOTES.md with detailed explanations of the implementation and important design decisions so I can understand the project when reviewing it later.

Do not commit or push changes without asking me first.
```

---

# 7. Claude Code – Day 3 Implementation

## Prompt 10: Predictive Maintenance Risk Engine and Evaluation

**Objective:** Build an explainable risk-scoring system and evaluate its ability to identify machine failures.

```text
Day 1 and Day 2 are complete, and all 60 existing tests are passing.

Now implement Day 3: Predictive Maintenance Risk Engine and Evaluation.

First inspect the existing repository and understand the architecture, datasets, telemetry, failures, maintenance records, and validation system.

Reuse the existing implementation instead of rebuilding it.

Implement the following:

1. Feature engineering using sensor trends, rolling averages, temperature, vibration, operating hours, machine age, and maintenance history.

2. An explainable risk engine that assigns each machine a score from 0–100, a risk level, reasons for the score, and recommended actions.

3. Evaluation using precision, recall, F1-score, false-positive rate, confusion matrix, and failure detection lead time.

4. Chronological training, validation, and testing splits to prevent data leakage.

5. Automated tests and documentation covering methodology, assumptions, results, and limitations.

Important constraints:

- Never use future data or ground-truth labels as input features.
- Keep the implementation reproducible.
- Preserve all existing functionality and passing tests.
- Do not hardcode evaluation results.
- Follow the existing project structure and coding conventions.
- Do not build a dashboard yet.

First inspect the project and provide a short implementation plan. Then implement Day 3 incrementally, run all tests, fix issues, and report the final results.

Do not commit or push changes without asking me first.
```

---

# 8. Claude Code – Final Documentation and Submission

## Prompt 11: AI Usage Disclosure and Limitations Review

**Objective:** Document AI assistance transparently and identify missing project assumptions or limitations.

```text
Create an AI_USAGE.md file in the project documentation.

Include:

- AI tools used during development.
- The areas where AI assistance was used.
- How the generated code was reviewed, tested, and corrected.
- Where the prompt history is documented.
- A statement explaining my responsibility for reviewing and validating the final implementation.

Keep the disclosure transparent and factual. Do not invent development activities or claim that I independently implemented something if I used AI assistance.

Also review the existing project documentation, assumptions, and implementation.

Identify any missing assumptions, technical limitations, design weaknesses, or areas that should be documented before submission.

Provide a clear list of the findings and suggest what should be updated.
```

## Prompt 12: Consolidating Project Limitations

**Objective:** Create a single document containing the project's known limitations and future improvements.

```text
Review the project and consolidate its known limitations into docs/limitations.md.

Organize the limitations into meaningful categories, including:

- Synthetic data and simulation assumptions.
- Maintenance processes and resource management.
- Sensor faults and data validation.
- Predictive maintenance risk engine.
- Scalability and execution environment.

For each limitation, explain:

1. What the limitation is.
2. Why it matters.
3. What could be improved in a future version.

Include the limitations already identified during implementation and testing. Do not hide known issues or introduce unsupported claims.

Also add a short Limitations section to the README with the most important points and a link to the detailed document.

Keep the documentation clear, concise, and consistent with the actual implementation.
```

## Prompt 13: Reviewing the Personal AI Usage Statement

**Objective:** Review and improve the personal reflection in AI_USAGE.md.

```text
I have written the following personal review for AI_USAGE.md.

Review it for clarity, natural language, and accuracy.

Make it sound like a genuine personal reflection rather than an overly formal AI-generated statement.

Preserve the meaning and do not exaggerate my individual contribution.

My review:

"I reviewed the generated code and the overall project flow to understand how each part works. I tested the implementation at different stages, checked the generated data, and fixed issues whenever the tests or validation identified problems.

I also reviewed the risk scores and evaluation results to understand where the system performs well and where it has limitations. AI tools helped me with implementation ideas, debugging, code improvements, and documentation, but I took responsibility for reviewing and testing the final work.

This project helped me understand how to build a complete data-generation and predictive maintenance workflow, from creating realistic industrial data to validating it and evaluating machine failure risks. I also learned the importance of reproducibility, data quality, avoiding data leakage, and documenting limitations honestly."

Suggest any changes needed to make the statement more accurate and natural.
```

---

# 9. Development Summary

The prompts above cover the main stages of the project:

| Phase | Main Deliverable |
|---|---|
| Planning | Requirement analysis and architecture |
| Technology selection | Python, database, and tooling decisions |
| Day 1 | Master data and telemetry generation |
| Day 2 | Failures, maintenance, sensor faults, anomalies, and validation |
| Day 3 | Feature engineering, risk scoring, and evaluation |
| Final documentation | AI usage disclosure, assumptions, and limitations |

**Documentation note:** The prompt history records the development instructions given to AI tools. The implementation, generated data, validation results, and final evaluation are documented separately in the project README and supporting documentation.

