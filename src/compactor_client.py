import logging
from openai import OpenAI
from pathlib import Path

from .config import get_backend_config, get_max_input_tokens, get_automation_config
from .extractor import pre_filter, is_prose
from .chunker import estimate_tokens
from .code_extractor import extract_skeleton

logger = logging.getLogger("prompt-compactor.client")

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


class CompactorClient:
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

    def outline_code(self, skeleton: str) -> str:
        """Convert a code skeleton to natural language outlines.
        Returns the skeleton unchanged on failure (never None or empty)."""
        result = self._call("code_outline", skeleton, max_tokens=400)
        if result and result.strip():
            return result.strip()
        return skeleton

    def compress(self, text: str, language: str = "python") -> str:
        """Compress text. Returns original on failure.

        Tiered pipeline based on input size:
        - Short (<300 tokens, prose): extractive-only — no LLM call, instant.
        - Medium (300–extractive_threshold tokens): Gemma abstractive only.
        - Large (>extractive_threshold tokens, prose): TF-IDF pre-filter → Gemma.

        Optional quality verification (quality_check config key):
        - After Gemma compresses, a second verify call confirms key facts survived.
          If the check fails, the original is returned instead.
        """
        automation = get_automation_config()
        original = text

        # Code path: AST skeleton extraction, optionally NL outline via Gemma.
        # Runs before the prose pipeline — code is never a good fit for TF-IDF.
        if not is_prose(text):
            skeleton = extract_skeleton(text, language)
            if skeleton is not text:  # extract_skeleton returns original when it can't help
                if len(skeleton.split()) > 200:
                    return self.outline_code(skeleton)
                return skeleton
            return original

        tokens = estimate_tokens(text)
        threshold = int(automation.get("extractive_threshold", 500))

        # Short prose: extractive-only, skip the LLM entirely
        # Only applies when pre_filter actually reduces the text (requires 4+ sentences).
        # If it can't compress (e.g. single-sentence input), fall through to Gemma.
        EXTRACTIVE_ONLY_LIMIT = 300
        if tokens <= EXTRACTIVE_ONLY_LIMIT and is_prose(text):
            filtered = pre_filter(text)
            if filtered and len(filtered) < len(text):
                logger.debug(f"Tiered: extractive-only for {tokens}-token input")
                return filtered

        # Large prose: pre-filter before sending to Gemma
        if tokens > threshold and is_prose(text):
            text = pre_filter(text)
            logger.debug(f"Tiered: extractive pre-filter applied; {tokens} → {estimate_tokens(text)} tokens")

        result = self._call("compress", text)
        if not result or not result.strip():
            return original

        if automation.get("quality_check", False):
            if not self.verify(original, result):
                logger.warning("Quality check failed — returning original text")
                return original

        return result

    def verify(self, original: str, compressed: str) -> bool:
        """Check whether `compressed` faithfully preserves all key facts from `original`.

        Returns True if the compression is faithful, False if important information
        was dropped or distorted. Returns True on LLM failure (fail-open) so a
        broken verify call never silently discards a valid compression.
        """
        prompt = f"ORIGINAL:\n{original}\n\nCOMPRESSED:\n{compressed}"
        result = self._call("verify", prompt, max_tokens=60)
        if result is None:
            logger.warning("verify() call failed — assuming faithful (fail-open)")
            return True
        first_line = result.strip().splitlines()[0].strip().upper()
        return not first_line.startswith("NO")

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

    def summarize(self, text: str, max_tokens: int = RESPONSE_BUDGET) -> str:
        """Summarize text. Returns truncated original on failure.
        max_tokens: cap on LLM response length; use for adaptive budget in generate_handoff."""
        result = self._call("summarize", text, max_tokens=max_tokens)
        if result and result.strip():
            return result
        # Fallback: return first SUMMARY_FALLBACK_CHARS chars
        return text[:SUMMARY_FALLBACK_CHARS] + " [... summarization failed, truncated ...]" if len(text) > SUMMARY_FALLBACK_CHARS else text

    def summarize_file(self, content: str) -> str:
        """Generate a one-line description of a file's purpose.
        Returns the first line of the model's response, or empty string on failure."""
        result = self._call("file_summary", content, max_tokens=60)
        if result and result.strip():
            return result.strip().splitlines()[0].strip()
        return ""
