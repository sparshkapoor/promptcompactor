import logging
from openai import OpenAI
from pathlib import Path

logger = logging.getLogger("apfel-context.client")

# Valid classification categories
VALID_CATEGORIES = frozenset({"progress", "bug", "decision", "architecture"})
DEFAULT_CATEGORY = "progress"

# Token budget constants for 4096 total context
SYSTEM_PROMPT_BUDGET = 300
RESPONSE_BUDGET = 1000
MAX_INPUT_TOKENS = 2500
MAX_INPUT_CHARS = MAX_INPUT_TOKENS * 4


class ApfelClient:
    def __init__(self, base_url: str = "http://localhost:11434/v1", timeout: float = 30.0):
        self.client = OpenAI(
            base_url=base_url,
            api_key="unused",
            timeout=timeout,
            max_retries=2
        )
        self.prompts_dir = Path(__file__).parent.parent / "prompts"

    def _load_prompt(self, name: str) -> str:
        filepath = self.prompts_dir / f"{name}.txt"
        if not filepath.exists():
            logger.error(f"Prompt file not found: {filepath}")
            raise FileNotFoundError(f"Missing prompt file: {filepath}")
        return filepath.read_text().strip()

    def _truncate_input(self, text: str) -> str:
        """Truncate input to fit within apfel's context window."""
        if len(text) <= MAX_INPUT_CHARS:
            return text
        logger.warning(f"Input truncated from {len(text)} to {MAX_INPUT_CHARS} chars")
        return text[:MAX_INPUT_CHARS] + "\n[... input truncated to fit context window ...]"

    def _call(self, prompt_name: str, user_content: str, max_tokens: int = RESPONSE_BUDGET) -> str | None:
        """Make a chat completion call to apfel. Returns None on failure."""
        try:
            system_prompt = self._load_prompt(prompt_name)
            truncated = self._truncate_input(user_content)

            resp = self.client.chat.completions.create(
                model="apple-foundationmodel",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": truncated}
                ],
                max_tokens=max_tokens,
                temperature=0.3
            )

            result = resp.choices[0].message.content
            if result is None:
                logger.warning(f"apfel returned None for prompt '{prompt_name}' — possible content filter")
                return None
            return result

        except FileNotFoundError:
            raise  # Let missing prompt files propagate
        except Exception as e:
            logger.error(f"apfel call failed ({prompt_name}): {type(e).__name__}: {e}")
            return None

    def compress(self, text: str) -> str:
        """Compress text. Returns original on failure."""
        result = self._call("compress", text)
        return result if result and result.strip() else text

    def classify(self, text: str) -> str:
        """Classify text into event category. Returns 'progress' on failure."""
        result = self._call("classify", text, max_tokens=10)
        if result is None:
            return DEFAULT_CATEGORY
        cleaned = result.strip().lower().rstrip(".")
        if cleaned in VALID_CATEGORIES:
            return cleaned
        logger.warning(f"Unexpected classification '{cleaned}', defaulting to '{DEFAULT_CATEGORY}'")
        return DEFAULT_CATEGORY

    def summarize(self, text: str) -> str:
        """Summarize text. Returns truncated original on failure."""
        result = self._call("summarize", text)
        if result and result.strip():
            return result
        # Fallback: return first 500 chars
        return text[:500] + " [... summarization failed, truncated ...]" if len(text) > 500 else text
