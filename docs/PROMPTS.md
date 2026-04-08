# Prompts

The `prompts/` directory contains the system prompts injected before each apfel call. Customising these is the primary way to tune the quality and style of compaction output.

## Files

| File | Used by | Purpose |
|------|---------|---------|
| `compress.txt` | `compact_prompt` | Removes filler while preserving all technical terms |
| `classify.txt` | `log_event(auto)` | Classifies a message into one of four event categories |
| `summarize.txt` | `summarize_history`, `generate_handoff` | Converts verbose text into bullet-point summaries |
| `extract.txt` | (reserved) | Extracts structured technical facts |

## Token Budget Constraints

apfel has a **4,096-token context window** shared between input and output. Each system prompt consumes tokens from this budget:

- System prompt budget: **~300 tokens** (keep each prompt file under 80 words)
- Model response budget: **~1,000 tokens**
- Safety margin: **~300 tokens**
- Available for user input: **~2,500 tokens**

Keeping prompts concise is critical. Every token spent on the system prompt directly reduces the input you can process in one call.

## How to Customise

Edit any `.txt` file directly. Changes take effect on the next tool call — no restart required.

**Rules:**
1. Keep each file under 80 words
2. Be explicit about output format (single word, bullet points, compressed text, etc.)
3. Explicitly instruct the model to preserve technical content (code, paths, error messages)
4. Avoid hedging language in the prompt itself — apfel will mirror it back

## classify.txt Special Format

The classify prompt must produce exactly one of four lowercase words:

- `progress` — task completed or work done
- `bug` — issue found or fixed
- `decision` — design or technology choice made
- `architecture` — note about codebase structure

Any other response defaults to `progress`. If you add new categories, you must also update `VALID_TYPES` in `src/state_manager.py` and `VALID_CATEGORIES` in `src/apfel_client.py`.
