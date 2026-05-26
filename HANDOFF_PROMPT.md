# PromptCompactor-Style Project Tracking — Handoff Prompt

> **How to use:** Paste everything below the horizontal rule into a new Claude Code session
> in the target project directory. Claude will detect the project type and set up the
> full tracking system automatically.

---

# SET UP LIVE PROJECT TRACKING FOR THIS DIRECTORY

You are being asked to bootstrap a persistent, self-updating tracking system for this project,
modelled after PromptCompactor. Do this now, in one session. Do not ask before starting.

## Step 1 — Read the project and identify its type

Scan the project root: look at file extensions, `package.json` / `pyproject.toml` /
`Cargo.toml` / `pom.xml`, top-level README, and any existing docs. From that, classify
the project into **one primary type** and note any secondary traits:

| Type label | Signals |
|---|---|
| `fin-ml` | tickers, OHLCV data, buy/sell signals, backtest, alpha, PnL |
| `web-app` | routes, components, API endpoints, auth, DB schema |
| `data-pipeline` | ETL, DAGs, transforms, sources/sinks, schemas |
| `cli-tool` | argparse/click/cobra, subcommands, man-page, install script |
| `ml-training` | model arch, loss curves, hyperparams, checkpoints, eval metrics |
| `library-sdk` | public API surface, versioning, docs, breaking changes |
| `infra-devops` | Terraform/K8s/Ansible, environments, deploy targets |
| `general` | everything else |

Write the type and a 1-sentence project description into the tracking files you create below.

## Step 2 — Create the folder structure

```
.claude/
  hooks/
    on-session-start.sh
    on-edit.sh
    on-stop.sh
  settings.json
  instructions.md       ← coding rules + DO/DON'T, tailored to project type
  CLAUDE.md             ← (if none exists) architecture + key rules

state/
  progress.md           ← timestamped log of every work session
  codebase.md           ← one-liner per source file, auto-updated on edit
  domain.md             ← PROJECT-TYPE-SPECIFIC live state (see Step 4)
  .edit_this_turn       ← sidecar flag file (touch/rm, do not put content)
```

Create all directories and files. If any already exist, append/merge — do not overwrite.

## Step 3 — Write the four hooks

### `.claude/hooks/on-session-start.sh`
Runs **synchronously** at session start. Its stdout is prepended to Claude's context.

```bash
#!/bin/bash
# Inject project state at session start.
cd "$(dirname "$0")/../.." || exit 0

echo "## Project State (auto-loaded)"
echo ""

# --- progress.md: last 30 lines ---
if [ -f state/progress.md ]; then
    echo "### Recent Progress"
    tail -30 state/progress.md
    echo ""
fi

# --- codebase.md: full ---
if [ -f state/codebase.md ]; then
    echo "### Codebase Map"
    cat state/codebase.md
    echo ""
fi

# --- domain.md: full ---
if [ -f state/domain.md ]; then
    echo "### Domain State"
    cat state/domain.md
    echo ""
fi

exit 0
```

### `.claude/hooks/on-edit.sh`
Runs **async** after every Edit / Write / MultiEdit tool use.

```bash
#!/bin/bash
# Log file edits and update codebase map.
cd "$(dirname "$0")/../.." || exit 0

FILE_PATH=$(cat | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ti = data.get('tool_input') or data
    print(ti.get('file_path') or ti.get('path') or '', end='')
except Exception:
    pass
" 2>/dev/null)

if [ -n "$FILE_PATH" ]; then
    # Set sidecar flag so on-stop.sh knows an edit happened
    touch state/.edit_this_turn

    # Append to progress log (timestamp + file)
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
    echo "- [$TIMESTAMP] Edited $FILE_PATH" >> state/progress.md
fi

exit 0
```

### `.claude/hooks/on-stop.sh`
Runs **async** after Claude finishes each response turn.

```bash
#!/bin/bash
# Log a turn summary only if edits happened this turn.
cd "$(dirname "$0")/../.." || exit 0

if [ -f state/.edit_this_turn ]; then
    rm -f state/.edit_this_turn
    echo "- [$(date '+%Y-%m-%d %H:%M')] Turn completed" >> state/progress.md
fi

exit 0
```

Make all three scripts executable: `chmod +x .claude/hooks/*.sh`

### `.claude/settings.json`

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "", "hooks": [{ "type": "command", "command": ".claude/hooks/on-session-start.sh" }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|MultiEdit|Write", "hooks": [{ "type": "command", "command": ".claude/hooks/on-edit.sh", "async": true }] }
    ],
    "Stop": [
      { "matcher": "", "hooks": [{ "type": "command", "command": ".claude/hooks/on-stop.sh", "async": true }] }
    ]
  }
}
```

## Step 4 — Create `state/domain.md` (PROJECT-TYPE SPECIFIC)

This is the most important part. Based on the project type you detected in Step 1,
seed `state/domain.md` with the right structure. You must fill in real values from
the actual codebase — not placeholders.

---

### If type = `fin-ml`

```markdown
# Domain State — Financial ML

## Model & Strategy
- **Architecture:** [e.g. LSTM / Transformer / XGBoost / ensemble]
- **Prediction target:** [e.g. next-bar return, 5-day price direction, volatility]
- **Signal type:** [e.g. long/short, binary buy-sell, confidence score 0–1]
- **Universe:** [tickers / instruments / timeframe]
- **Features:** [list top 5-10 input features: RSI, MACD, volume z-score, etc.]

## Current Backtest Results
| Metric | Value | As of |
|---|---|---|
| Sharpe ratio | — | — |
| Max drawdown | — | — |
| Win rate | — | — |
| Annualised return | — | — |
| Total trades | — | — |

## Algorithm Decisions Log
<!-- One entry per significant algo change. Most recent first. -->
<!-- Format: [date] Change → Reason → Impact -->

## Open Questions / Next Experiments
- [ ] ...

## Data Pipeline Status
- Source: [e.g. Yahoo Finance / Alpaca / CSV files]
- Feature engineering: [file path]
- Train/val/test split: [dates or ratios]
- Last data refresh: —
```

---

### If type = `web-app`

```markdown
# Domain State — Web App

## Architecture
- **Stack:** [frontend / backend / DB]
- **Auth:** [method]
- **Key routes:** [list]
- **External services:** [list APIs / queues / caches]

## Feature Status
| Feature | Status | Notes |
|---|---|---|
| ... | planned / in-progress / done | |

## Schema Changes Log
<!-- Most recent first -->

## Open Bugs / Decisions
- [ ] ...
```

---

### If type = `ml-training`

```markdown
# Domain State — ML Training

## Model
- **Architecture:** [layers, params, framework]
- **Task:** [classification / regression / generation]
- **Dataset:** [name, size, split]

## Training Runs Log
| Run | Epochs | Loss | Val metric | Notes |
|---|---|---|---|---|
| ... | | | | |

## Hyperparameter Decisions
<!-- What was tried, what was kept, why -->

## Checkpoints
- Best checkpoint: —
- Latest checkpoint: —

## Open Experiments
- [ ] ...
```

---

### If type = `data-pipeline`

```markdown
# Domain State — Data Pipeline

## Pipeline Overview
- **Orchestrator:** [Airflow / Prefect / cron / manual]
- **Sources:** [list]
- **Sinks:** [list]
- **Schedule:** [cron or trigger]

## DAG / Job Status
| Job | Last run | Status | Notes |
|---|---|---|---|
| ... | | | |

## Schema Registry
<!-- Table names / topic names + field list for key schemas -->

## Open Issues
- [ ] ...
```

---

### If type = `general` or anything else

```markdown
# Domain State — [Project Name]

## What This Does
[1-2 sentences]

## Key Components
| Component | File(s) | Purpose |
|---|---|---|
| ... | | |

## Decision Log
<!-- Most recent first. Format: [date] Decision → Reason -->

## Open Work
- [ ] ...
```

---

## Step 5 — Seed `state/codebase.md`

Walk every source file (exclude node_modules, .venv, dist, build, __pycache__, .git).
For each file write one line:

```
- `path/to/file.ext`: One sentence describing exactly what this file does.
```

Keep descriptions factual — what the file *does*, not what it *is*.

## Step 6 — Seed `state/progress.md`

Create the first entry:

```markdown
# Progress Log

## [TODAY'S DATE] (session 1 — bootstrap)
- [DONE] Created .claude/hooks/ and state/ tracking structure
- [DONE] Detected project type: [TYPE]
- [DONE] Seeded state/domain.md with project-specific fields
- [DONE] Seeded state/codebase.md with [N] file entries
- [NOTE] [One sentence about the biggest open unknown in this codebase right now]
```

## Step 7 — Write `.claude/instructions.md`

Tailor these rules to the detected project type. Always include:

```markdown
# Instructions for Claude Working on This Project

## Session Hygiene
- Update `state/progress.md` with a dated session entry before every git commit.
- Update `state/domain.md` whenever an algorithm, model, schema, or key decision changes.
- Update `state/codebase.md` whenever a new file is created or an existing file's purpose changes.
- At session start, read `state/domain.md` before exploring source files — it is the source of truth for current project state.

## Progress Entry Format
Each session entry should include:
- What was done (prefix [DONE])
- What was decided and why (prefix [DECIDED])
- What is still open (prefix [NOTE] or [ ] checkbox)
- If fin-ml: include metric deltas when a model or feature change was made

## [Add project-type-specific rules here]
```

## Step 8 — Ongoing: keep domain.md updated

**This is the most important rule.** Every time you make a change that affects project-type-specific state, update `state/domain.md` immediately in the same turn:

- **fin-ml:** Update the backtest table when you run a backtest. Log every feature/algo change in "Algorithm Decisions Log". Update "Open Questions" when an experiment is designed or completed.
- **web-app:** Update feature status table. Log every schema migration.
- **ml-training:** Log every training run with at least loss + val metric. Record hyperparameter decisions.
- **data-pipeline:** Update job status after every run.
- **general:** Log every significant decision with date and reason.

The goal: any new session should be able to read `state/domain.md` alone and understand *exactly* where the project stands — no source-code archaeology needed.

---

## What "easily readable" means here

Format domain.md so it passes the "5-second test": a developer skimming it for 5 seconds
should know:
1. What the project does
2. What the current best result is (for fin-ml: Sharpe / win rate; for ml: val loss / accuracy)
3. What is being worked on right now
4. What the last 2-3 decisions were and why

Use tables for numeric state. Use checkboxes for open work. Use `[DONE]` / `[DECIDED]` / `[NOTE]` prefixes in progress.md so it's scannable. Never write walls of prose.

---

**Start now.** Read the project, fill in real values, create all files. Report back with:
- Detected project type
- Number of files mapped in codebase.md
- The filled-in domain.md (so I can verify it's real, not placeholder)
