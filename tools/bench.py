#!/usr/bin/env python3
"""
bench.py — Token count + compression benchmark for PromptCompactor.

Compares raw token count vs compressed output across backends (Gemma, apfel, etc.).
Measures latency and output tokens/sec so you can see exactly what the compressor buys you.

Usage:
    echo "some verbose text" | python tools/bench.py
    python tools/bench.py -f my_prompt.txt
    python tools/bench.py --sample                     # run against built-in sample prompts
    python tools/bench.py --model apple-foundationmodel --url http://localhost:11434/v1
    python tools/bench.py --show-output                # print compressed text after table
    python tools/bench.py --warmup                     # fire a dummy call first; report load ms + TTFT
"""

import argparse
import sys
import time
import os
from pathlib import Path
from typing import NamedTuple

import tiktoken
from openai import OpenAI

# ── path setup so we can import src/ without installing the package ─────────
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from src.compactor_client import CompactorClient  # noqa: E402

# ── tokenizer setup ──────────────────────────────────────────────────────────
# cl100k_base is a reasonable general-purpose approximation.
# Gemma uses a SentencePiece BPE, so counts will differ slightly, but this is
# the best portable option without pulling in the full Gemma tokenizer.
_ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


# ── built-in sample prompts for quick --sample runs ──────────────────────────
SAMPLES = {
    "verbose_task": (
        "I would like you to please help me with a task that I have been trying to figure out "
        "for quite some time now. Essentially what I need you to do is to take a look at the "
        "existing Python codebase that we have and refactor the authentication module so that "
        "it properly handles JWT token validation, because right now it seems like it is not "
        "working correctly and users are getting logged out unexpectedly after about 15 minutes "
        "or so, which is definitely not the intended behavior according to our requirements doc."
    ),
    "tool_output": (
        "Tool: bash\nOutput:\n"
        "total 128\n-rw-r--r--  1 user staff  4096 Apr 11 10:00 README.md\n"
        "-rw-r--r--  1 user staff  8192 Apr 11 10:01 requirements.txt\n"
        "-rw-r--r--  1 user staff 12288 Apr 11 10:02 pyproject.toml\n"
        "drwxr-xr-x  5 user staff   160 Apr 11 10:03 src\n"
        "drwxr-xr-x  3 user staff    96 Apr 11 10:03 tests\n"
        "drwxr-xr-x  2 user staff    64 Apr 11 10:04 prompts\n"
        "drwxr-xr-x  2 user staff    64 Apr 11 10:05 state\n"
        "\nCommand completed successfully with exit code 0. No errors were detected.\n"
        "The operation finished at 10:05:33 and took approximately 0.043 seconds total."
    ),
    "long_explanation": (
        "The reason why we need to implement chunking here is that the underlying model we are "
        "using has a context window limitation. When we pass text that exceeds this limitation, "
        "the model will either raise an error or silently truncate the input, neither of which "
        "is acceptable behavior for a production system. By implementing chunking, we split the "
        "input into smaller pieces that each fit within the model's context window, process each "
        "piece independently, and then concatenate the results. This approach ensures that no "
        "information is lost due to truncation. The chunk size should be set conservatively, "
        "leaving room for the system prompt and the model's response, to avoid any edge cases "
        "where a chunk barely fits but causes issues in combination with the system prompt overhead."
    ),
}


# ── result container ──────────────────────────────────────────────────────────
class BenchResult(NamedTuple):
    label: str
    input_tokens: int
    output_tokens: int
    warmup_ms: float    # dummy-call latency to detect cold start; -1 if --warmup not used
    ttft_ms: float      # time to first token of the real call; -1 if not measured
    total_ms: float     # end-to-end latency of the real call; -1 for baseline
    output_text: str    # compressed text (same as input for baseline)

    # ── derived ──────────────────────────────────────────────────────────────

    @property
    def ratio(self) -> str:
        if self.total_ms < 0:
            return "—"
        if self.input_tokens == 0:
            return "—"
        pct = (1 - self.output_tokens / self.input_tokens) * 100
        return f"{pct:+.1f}%"

    @property
    def gen_ms(self) -> float:
        """Pure generation time: total minus TTFT."""
        if self.total_ms < 0:
            return -1
        if self.ttft_ms >= 0:
            return max(0.0, self.total_ms - self.ttft_ms)
        return self.total_ms

    @property
    def gen_tok_per_sec(self) -> str:
        gen = self.gen_ms
        if gen <= 0:
            return "—"
        # subtract 1 token because TTFT already produced the first one
        gen_tokens = max(1, self.output_tokens - 1)
        return f"{gen_tokens / (gen / 1000):.1f}"


# ── low-level helpers ─────────────────────────────────────────────────────────

def _make_client(base_url: str, timeout: float = 60.0) -> OpenAI:
    return OpenAI(base_url=base_url, api_key="unused", timeout=timeout)


def _warmup_call(client: OpenAI, model: str) -> float:
    """
    Send a minimal 1-token completion to force model load.
    Returns elapsed ms.  Uses a non-streaming call so it's simple.
    """
    t0 = time.perf_counter()
    client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "."}],
        max_tokens=1,
        temperature=0.0,
    )
    return (time.perf_counter() - t0) * 1000


def _call_streaming(client: OpenAI, model: str, system: str, user: str) -> tuple[str, float, float]:
    """
    Stream a chat completion.
    Returns (full_text, ttft_ms, total_ms).
    ttft_ms is the wall-clock time until the first content chunk arrives.
    """
    t0 = time.perf_counter()
    ttft_ms = -1.0
    chunks: list[str] = []

    with client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=2000,
        temperature=0.3,
        stream=True,
    ) as stream:
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                if ttft_ms < 0:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                chunks.append(delta)

    total_ms = (time.perf_counter() - t0) * 1000
    return "".join(chunks), ttft_ms, total_ms


# ── benchmark logic ───────────────────────────────────────────────────────────

def run_benchmark(text: str, model: str, base_url: str, do_warmup: bool) -> BenchResult:
    client = _make_client(base_url)
    prompt_path = _REPO_ROOT / "prompts" / "compress.txt"
    system_prompt = prompt_path.read_text().strip()

    input_tokens = count_tokens(text)

    warmup_ms = -1.0
    if do_warmup:
        warmup_ms = _warmup_call(client, model)

    compressed, ttft_ms, total_ms = _call_streaming(client, model, system_prompt, text)
    output_tokens = count_tokens(compressed)

    return BenchResult(
        label=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        warmup_ms=warmup_ms,
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        output_text=compressed,
    )


def baseline(text: str) -> BenchResult:
    toks = count_tokens(text)
    return BenchResult(
        label="(no compression)",
        input_tokens=toks,
        output_tokens=toks,
        warmup_ms=-1,
        ttft_ms=-1,
        total_ms=-1,
        output_text=text,
    )


# ── display ───────────────────────────────────────────────────────────────────

def _ms(val: float) -> str:
    return f"{val:.0f}" if val >= 0 else "—"


def print_results(label: str, results: list[BenchResult], show_output: bool, do_warmup: bool) -> None:
    print(f"\n=== {label} ===")
    print(f"Input: {results[0].input_tokens} tokens  ({len(results[0].output_text)} chars)\n")

    if do_warmup:
        # Extended table with warmup, TTFT, gen speed
        hdr = (
            f"{'Model':<24} {'In':>6} {'Out':>6} {'Δ':>7} "
            f"{'warmup ms':>10} {'ttft ms':>8} {'gen ms':>8} {'gen tok/s':>10}"
        )
        sep = "-" * len(hdr)
        print(hdr)
        print(sep)
        for r in results:
            print(
                f"{r.label:<24} {r.input_tokens:>6} {r.output_tokens:>6} {r.ratio:>7} "
                f"{_ms(r.warmup_ms):>10} {_ms(r.ttft_ms):>8} {_ms(r.gen_ms):>8} {r.gen_tok_per_sec:>10}"
            )
    else:
        # Original compact table
        hdr = (
            f"{'Model':<24} {'In tok':>9} {'Out tok':>9} {'Δ tokens':>9} {'ms':>9} {'tok/s':>10}"
        )
        sep = "-" * len(hdr)
        print(hdr)
        print(sep)
        for r in results:
            ms_str = _ms(r.total_ms)
            # tok/s = output tokens / total seconds (original behaviour)
            if r.total_ms > 0:
                tps = f"{r.output_tokens / (r.total_ms / 1000):.1f}"
            else:
                tps = "—"
            print(
                f"{r.label:<24} {r.input_tokens:>9} {r.output_tokens:>9} "
                f"{r.ratio:>9} {ms_str:>9} {tps:>10}"
            )

    print()

    if show_output:
        for r in results:
            if r.total_ms >= 0:
                print(f"── {r.label} output ──")
                print(r.output_text)
                print()


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark PromptCompactor compression: token count, ratio, and latency."
    )
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("-f", "--file", type=Path, help="Read input text from file")
    input_group.add_argument("--sample", action="store_true", help="Run against built-in sample prompts")

    parser.add_argument(
        "--model",
        default=os.environ.get("APFEL_MODEL", "gemma4:e4b"),
        help="Model to benchmark (default: gemma4:e4b or $APFEL_MODEL)",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("APFEL_BASE_URL", "http://localhost:11434/v1"),
        help="Ollama/apfel base URL (default: http://localhost:11434/v1 or $APFEL_BASE_URL)",
    )
    parser.add_argument(
        "--also",
        metavar="MODEL",
        action="append",
        default=[],
        help="Additional model to compare (repeatable, e.g. --also apple-foundationmodel)",
    )
    parser.add_argument(
        "--show-output",
        action="store_true",
        help="Print compressed text after the table",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help=(
            "Fire a 1-token dummy call per model before benchmarking. "
            "Reveals cold-start load time and separates TTFT from pure generation speed."
        ),
    )
    args = parser.parse_args()

    models: list[tuple[str, str]] = [(args.model, args.url)]
    for extra in args.also:
        models.append((extra, args.url))

    # ── collect inputs ────────────────────────────────────────────────────────
    if args.sample:
        inputs = SAMPLES
    elif args.file:
        text = args.file.read_text()
        inputs = {args.file.name: text}
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
        inputs = {"stdin": text}
    else:
        parser.print_help()
        print("\nNo input provided. Use --sample for a quick demo, pipe text, or -f <file>.")
        sys.exit(1)

    # ── run benchmarks ────────────────────────────────────────────────────────
    for name, text in inputs.items():
        results: list[BenchResult] = [baseline(text)]
        for model, url in models:
            warmup_label = " (warmup + " if args.warmup else " ("
            print(f"  Running {model}...{warmup_label}streaming)...", end="", flush=True)
            try:
                result = run_benchmark(text, model, url, do_warmup=args.warmup)
                if args.warmup:
                    print(f" done  [warmup {result.warmup_ms:.0f}ms | ttft {result.ttft_ms:.0f}ms | total {result.total_ms:.0f}ms]")
                else:
                    print(f" done ({result.total_ms:.0f}ms)")
                results.append(result)
            except Exception as e:
                print(f" FAILED: {e}")

        print_results(name, results, args.show_output, do_warmup=args.warmup)


if __name__ == "__main__":
    main()
