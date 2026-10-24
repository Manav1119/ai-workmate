# User personas

> **These personas are assumptions**, written from the product brief and general domain knowledge. They are not based on interviews or usage data. Each lists the assumptions that most need validating.

## 1. Priya — performance marketing analyst

- Owns daily reporting for 10–40 paid campaigns across Google, Meta and TikTok.
- Fluent in spreadsheets, comfortable but slow with SQL; spends Monday mornings explaining last week's movements.
- **Needs:** fast "what changed and where" with numbers she can paste into Slack without re-checking.
- **Frustrations:** CPA "averages" that don't match the platform; finding out on Wednesday that a tag broke on Saturday.
- **What AI Workmate gives her:** driver analysis with exact contributions, tracking-gap detection, exportable reports.
- *Assumptions to validate:* that she'd trust an AI answer if the SQL is visible; that campaign-day grain is sufficient.

## 2. Marcus — associate product manager

- Asked metric questions in reviews; not the owner of the data pipeline.
- **Needs:** a correct answer plus the caveats, so he doesn't over-claim.
- **Frustrations:** dashboards that show *that* something moved but not *where*; analysts' queues.
- **What AI Workmate gives him:** plain-English questions, facts vs hypotheses separation, limitations section.
- *Assumptions to validate:* that he reads limitations; that "possible explanations" don't get quoted as findings.

## 3. Dana — founder / operator

- Runs a small DTC brand; checks spend vs revenue a few times a week.
- **Needs:** "is anything broken or wasting money?" in under two minutes.
- **What AI Workmate gives her:** overview KPIs, anomaly monitor, daily briefing, high-spend-low-efficiency view.
- *Assumptions to validate:* willingness to upload CSVs; tolerance for statistical language (z-scores, baselines).

## Anti-persona

A data engineer looking for a general SQL IDE or BI replacement. AI Workmate deliberately restricts schema and operations.
