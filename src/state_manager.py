import logging
import re
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("apfel-context.state")

# Strict allowlist of valid state file types
VALID_TYPES = frozenset({"progress", "bug", "decision", "architecture"})

# Max size per state file (prevent unbounded growth)
MAX_FILE_SIZE_BYTES = 100_000  # ~100KB per file


class StateManager:
    def __init__(self, state_dir: str | Path | None = None):
        if state_dir:
            self.state_dir = Path(state_dir).resolve()
        else:
            self.state_dir = (Path(__file__).parent.parent / "state").resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _validate_type(self, event_type: str) -> str:
        """Validate and sanitize event type. Prevents path traversal."""
        # Strip any path separators, dots, or special chars
        cleaned = re.sub(r'[^a-z]', '', event_type.lower().strip())
        if cleaned not in VALID_TYPES:
            logger.warning(f"Invalid event type '{event_type}', defaulting to 'progress'")
            return "progress"
        return cleaned

    def _get_path(self, event_type: str) -> Path:
        """Get sanitized file path. Ensures it stays within state_dir."""
        safe_type = self._validate_type(event_type)
        filepath = (self.state_dir / f"{safe_type}.md").resolve()
        # Security: verify the resolved path is still inside state_dir
        if not filepath.is_relative_to(self.state_dir):
            raise ValueError(f"Path traversal detected: {filepath}")
        return filepath

    def append(self, event_type: str, content: str) -> None:
        """Append a timestamped entry to a state file."""
        filepath = self._get_path(event_type)

        # Check file size limit
        if filepath.exists() and filepath.stat().st_size > MAX_FILE_SIZE_BYTES:
            logger.warning(f"{filepath.name} exceeds {MAX_FILE_SIZE_BYTES} bytes, rotating")
            self._rotate(filepath)

        # Sanitize content: remove null bytes, limit length
        safe_content = content.replace("\x00", "").strip()
        if len(safe_content) > 5000:
            safe_content = safe_content[:5000] + " [... truncated ...]"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] {safe_content}\n"

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info(f"Logged to {filepath.name}: {safe_content[:80]}...")

    def read(self, event_type: str) -> str:
        """Read a state file. Returns empty string if not found or unreadable."""
        filepath = self._get_path(event_type)
        if filepath.exists():
            try:
                return filepath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.error(f"Non-UTF-8 bytes in {filepath.name}; returning empty string")
                return ""
        return ""

    def read_all(self) -> str:
        """Read all state files into a formatted string."""
        sections = []
        for t in sorted(VALID_TYPES):
            content = self.read(t)
            if content.strip():
                sections.append(f"## {t.title()}\n{content}")
        return "\n\n".join(sections) if sections else "No state files yet."

    def clear(self, event_type: str) -> None:
        """Clear a state file."""
        filepath = self._get_path(event_type)
        if filepath.exists():
            filepath.write_text("", encoding="utf-8")
            logger.info(f"Cleared {filepath.name}")

    def clear_all(self) -> None:
        """Clear all state files."""
        for t in VALID_TYPES:
            self.clear(t)

    def _rotate(self, filepath: Path) -> None:
        """Rotate a state file that's grown too large."""
        content = filepath.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        # Keep only the most recent half
        kept = lines[len(lines) // 2:]
        filepath.write_text("\n".join(kept) + "\n", encoding="utf-8")
        logger.info(f"Rotated {filepath.name}: kept {len(kept)}/{len(lines)} entries")
