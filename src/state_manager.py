import fcntl
import logging
import re
from contextlib import contextmanager
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

    @contextmanager
    def _locked(self, filepath: Path):
        """Acquire an exclusive advisory lock for the duration of the context.
        Uses a sidecar .lock file so lock acquisition doesn't interfere with
        the target file's open mode (append vs read-write)."""
        lock_path = filepath.parent / (filepath.name + ".lock")
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            yield
        # flock released when lf closes; lock file left in place (harmless, reused next time)

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

        # Sanitize content: remove null bytes, limit length
        safe_content = content.replace("\x00", "").strip()
        if len(safe_content) > 5000:
            safe_content = safe_content[:5000] + " [... truncated ...]"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] {safe_content}\n"

        # Lock covers size check + rotate + write to prevent TOCTOU races
        # between concurrent hook processes writing to the same file.
        with self._locked(filepath):
            if filepath.exists() and filepath.stat().st_size > MAX_FILE_SIZE_BYTES:
                logger.warning(f"{filepath.name} exceeds {MAX_FILE_SIZE_BYTES} bytes, rotating")
                self._rotate(filepath)
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

    def _codebase_path(self) -> Path:
        return (self.state_dir / "codebase.md").resolve()

    def update_file_summary(self, filepath: str, summary: str) -> None:
        """Upsert a filepath→summary entry in state/codebase.md.
        Creates the file if it doesn't exist. Thread-safe for single-line updates
        within OS PIPE_BUF limits; concurrent writes to different keys are safe."""
        safe_path = filepath.replace("\x00", "").strip()
        safe_summary = summary.replace("\x00", "").strip()
        if not safe_path or not safe_summary:
            return

        codebase_file = self._codebase_path()
        # Lock covers read-modify-write to prevent concurrent hook processes
        # from clobbering each other's updates to the shared codebase.md.
        with self._locked(codebase_file):
            if codebase_file.exists():
                lines = codebase_file.read_text(encoding="utf-8").splitlines()
            else:
                lines = ["# Codebase Map", ""]

            prefix = f"- `{safe_path}`:"
            new_line = f"- `{safe_path}`: {safe_summary}"
            for i, line in enumerate(lines):
                if line.startswith(prefix):
                    lines[i] = new_line
                    break
            else:
                lines.append(new_line)

            codebase_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"Updated codebase map: {safe_path}")

    def read_all(self) -> str:
        """Read all state files into a formatted string."""
        sections = []
        for t in sorted(VALID_TYPES):
            content = self.read(t)
            if content.strip():
                sections.append(f"## {t.title()}\n{content}")
        codebase_file = self._codebase_path()
        if codebase_file.exists():
            codebase_content = codebase_file.read_text(encoding="utf-8").strip()
            if codebase_content:
                sections.append(f"## Codebase\n{codebase_content}")
        return "\n\n".join(sections) if sections else "No state files yet."

    def read_narrative(self) -> str:
        """Read only VALID_TYPES state files (excludes codebase map).
        Used by generate_handoff to separate narrative from the structured map."""
        sections = []
        for t in sorted(VALID_TYPES):
            content = self.read(t)
            if content.strip():
                sections.append(f"## {t.title()}\n{content}")
        return "\n\n".join(sections) if sections else "No state files yet."

    # Max file entries to include verbatim from codebase.md in generate_handoff
    _MAX_CODEBASE_ENTRIES = 50

    def read_codebase(self, max_entries: int = _MAX_CODEBASE_ENTRIES) -> str:
        """Read state/codebase.md, returning the last max_entries file entries verbatim.
        Preserves header lines. Returns empty string if no codebase map exists.
        Codebase entries are never summarized — they are either included or truncated."""
        codebase_file = self._codebase_path()
        if not codebase_file.exists():
            return ""
        content = codebase_file.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        lines = content.splitlines()
        entry_lines = [line for line in lines if line.startswith("- ")]
        header_lines = [line for line in lines if not line.startswith("- ")]
        total = len(entry_lines)
        if total > max_entries:
            kept = entry_lines[-max_entries:]
            result = "\n".join(header_lines + kept)
            result += f"\n[... showing last {max_entries} of {total} entries ...]"
        else:
            result = "\n".join(header_lines + entry_lines)
        return result

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
