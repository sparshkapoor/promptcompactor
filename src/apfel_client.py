import logging
from openai import OpenAI
from pathlib import Path

from .config import get_backend_config, get_max_input_tokens

logger = logging.getLogger("apfel-context.client")

# Valid classification categories
VALID_CATEGORIES = frozenset({"progress", "bug", "decision", "architecture"})
DEFAULT_CATEGORY = "progress"

# Resolved at import time — env vars and config.json both handled by get_backend_config()
_backend = get_backend_config()
DEFAULT_MODEL = _backend["model"]
DEFAULT_BASE_URL = _backend["base_url"]

# Token budget: driven by config.json (max_context_tokens minus budget slices)
RESPONSE_BUDGET = 2000
MAX_INPUT_TOKENS = get_max_input_tokens()
MAX_INPUT_CHARS = MAX_INPUT_TOKENS * 4
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_RETRIES = 2
SUMMARY_FALLBACK_CHARS = 500


class ApfelClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
    ):
        self._timeout = timeout
        self.model = model
        self.prompts_dir = Path(__file__).parent.parent / "prompts"
        self._init_client(base_url)

    def _init_client(self, base_url: str) -> None:
        self._base_url = base_url
        self.client = OpenAI(
            base_url=base_url,
            api_key="unused",  # Ollama/apfel don't require auth; SDK requires a non-empty value
            timeout=self._timeout,
            max_retries=DEFAULT_MAX_RETRIES,
        )

    def reconfigure(self, model: str, base_url: str) -> None:
        """Switch model and/or base URL at runtime without restarting."""
        self.model = model
        if base_url != self._base_url:
            self._init_client(base_url)
            logger.info(f"Client reinitialized with base_url={base_url}")

    def _load_prompt(self, name: str) -> str:
        filepath = self.prompts_dir / f"{name}.txt"
        if not filepath.exists():
            logger.error(f"Prompt file not found: {filepath}")
            raise FileNotFoundError(f"Missing prompt file: {filepath}")
        return filepath.read_text().strip()

    def _truncate_input(self, text: str) -> str:
        """Truncate input to MAX_INPUT_CHARS as a safety ceiling. Logs a warning if triggered."""
        if len(text) <= MAX_INPUT_CHARS:
            return text
        logger.warning(f"Input truncated from {len(text)} to {MAX_INPUT_CHARS} chars")
        return text[:MAX_INPUT_CHARS] + "\n[... input truncated to fit context window ...]"

    def _call(self, prompt_name: str, user_content: str, max_tokens: int = RESPONSE_BUDGET) -> str | None:
        """Make a chat completion call to the local model. Returns None on failure."""
        try:
            system_prompt = self._load_prompt(prompt_name)
            truncated = self._truncate_input(user_content)

            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": truncated}
                ],
                max_tokens=max_tokens,
                temperature=DEFAULT_TEMPERATURE,
            )

            result = resp.choices[0].message.content
            if result is None:
                logger.warning(f"Model returned None for prompt '{prompt_name}' — possible content filter")
                return None
            return result

        except FileNotFoundError:
            raise  # Let missing prompt files propagate
        except Exception as e:
            logger.error(f"Model call failed ({prompt_name}): {type(e).__name__}: {e}")
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
        # Fallback: return first SUMMARY_FALLBACK_CHARS chars
        return text[:SUMMARY_FALLBACK_CHARS] + " [... summarization failed, truncated ...]" if len(text) > SUMMARY_FALLBACK_CHARS else text
