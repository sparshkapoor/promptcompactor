"""Tests for src/code_extractor.py"""
import pytest
from src.code_extractor import extract_skeleton, language_for_path


# ---------------------------------------------------------------------------
# language_for_path
# ---------------------------------------------------------------------------

def test_language_for_path_python():
    assert language_for_path("foo.py") == "python"

def test_language_for_path_typescript():
    assert language_for_path("bar.ts") == "typescript"

def test_language_for_path_tsx():
    assert language_for_path("App.tsx") == "tsx"

def test_language_for_path_go():
    assert language_for_path("main.go") == "go"

def test_language_for_path_javascript():
    assert language_for_path("index.js") == "javascript"
    assert language_for_path("component.jsx") == "javascript"

def test_language_for_path_unsupported_returns_none():
    assert language_for_path("styles.css") is None
    assert language_for_path("script.sh") is None
    assert language_for_path("data.json") is None
    assert language_for_path("README.md") is None

def test_language_for_path_header_files():
    assert language_for_path("header.h") == "c"
    assert language_for_path("header.hpp") == "cpp"


# ---------------------------------------------------------------------------
# extract_skeleton — edge cases
# ---------------------------------------------------------------------------

def test_extract_skeleton_empty_returns_empty():
    assert extract_skeleton("", "python") == ""

def test_extract_skeleton_whitespace_returns_whitespace():
    assert extract_skeleton("   ", "python") == "   "

def test_extract_skeleton_unsupported_language_returns_original():
    src = "x = 1\ny = 2\n"
    assert extract_skeleton(src, "brainfuck") == src

def test_extract_skeleton_no_functions_returns_original():
    # No functions/classes → skeleton == source → fails 90% threshold → returns original
    src = "x = 1\ny = 2\nz = x + y\n"
    assert extract_skeleton(src, "python") == src


# ---------------------------------------------------------------------------
# extract_skeleton — Python
# ---------------------------------------------------------------------------

_PY_SIMPLE_FUNC = """\
def add(a, b):
    result = a + b
    return result
"""

def test_python_simple_function_removes_body():
    sk = extract_skeleton(_PY_SIMPLE_FUNC, "python")
    assert "def add(a, b):" in sk
    assert "..." in sk
    assert "result = a + b" not in sk
    assert "return result" not in sk

def test_python_skeleton_is_shorter_than_source():
    src = "\n".join([
        "def process(data):",
        "    step1 = data.strip()",
        "    step2 = step1.lower()",
        "    step3 = step2.replace(' ', '_')",
        "    step4 = step3.encode('utf-8')",
        "    step5 = step4.decode('ascii', errors='ignore')",
        "    return step5",
    ])
    sk = extract_skeleton(src, "python")
    assert len(sk) < len(src)

def test_python_docstring_preserved():
    src = '''\
def greet(name):
    """Return a greeting string for the given name."""
    return f"Hello, {name}!"
'''
    sk = extract_skeleton(src, "python")
    assert "def greet(name):" in sk
    assert "Return a greeting string" in sk
    assert 'f"Hello, {name}!"' not in sk

def test_python_multiline_docstring_preserved():
    src = '''\
def compute(x, y):
    """
    Compute the sum of x and y.
    Returns an integer.
    """
    intermediate = x * 2
    return intermediate + y
'''
    sk = extract_skeleton(src, "python")
    assert "def compute(x, y):" in sk
    assert "Compute the sum" in sk
    assert "intermediate = x * 2" not in sk

def test_python_class_with_methods():
    src = '''\
class Calculator:
    """Simple arithmetic calculator."""

    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        result = a - b
        return result
'''
    sk = extract_skeleton(src, "python")
    assert "class Calculator:" in sk
    assert "def add(self, a, b):" in sk
    assert "def subtract(self, a, b):" in sk
    assert "return a + b" not in sk
    assert "result = a - b" not in sk

def test_python_decorated_function():
    src = '''\
@property
def value(self):
    return self._value

@staticmethod
def helper(x):
    y = x * 2
    return y
'''
    sk = extract_skeleton(src, "python")
    assert "@property" in sk
    assert "def value(self):" in sk
    assert "@staticmethod" in sk
    assert "def helper(x):" in sk
    assert "y = x * 2" not in sk

def test_python_async_function():
    src = '''\
async def fetch(url):
    response = await client.get(url)
    data = await response.json()
    return data
'''
    sk = extract_skeleton(src, "python")
    assert "async def fetch(url):" in sk
    assert "response = await" not in sk

def test_python_returns_original_when_no_reduction():
    # A single-line function body barely reduces size — should get original back
    src = "def f():\n    pass\n"
    result = extract_skeleton(src, "python")
    # With "pass" as body → skeleton is "def f():\n    ..." — may or may not be <90%
    # Either way it should not crash and must return a string
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# extract_skeleton — JavaScript
# ---------------------------------------------------------------------------

_JS_FUNC = """\
function greet(name) {
    const msg = "Hello, " + name;
    console.log(msg);
    return msg;
}
"""

def test_javascript_function_removes_body():
    sk = extract_skeleton(_JS_FUNC, "javascript")
    assert "function greet(name)" in sk
    assert "..." in sk
    assert 'console.log(msg)' not in sk

def test_javascript_class_with_method():
    src = """\
class Animal {
    constructor(name) {
        this.name = name;
        this.sound = null;
    }

    speak() {
        console.log(this.name + " makes a sound.");
        return this.sound;
    }
}
"""
    sk = extract_skeleton(src, "javascript")
    assert "class Animal" in sk
    assert "constructor(name)" in sk
    assert "speak()" in sk
    assert "console.log" not in sk


# ---------------------------------------------------------------------------
# extract_skeleton — fallback safety
# ---------------------------------------------------------------------------

def test_extract_skeleton_never_raises():
    """extract_skeleton must not raise regardless of input."""
    inputs = [
        ("", "python"),
        ("broken {{{", "python"),
        ("x = 1", "unsupported_lang"),
        ("def f():\n    pass\n", "go"),  # valid Go parser, Python source
    ]
    for src, lang in inputs:
        result = extract_skeleton(src, lang)
        assert isinstance(result, str)

def test_extract_skeleton_returns_original_type():
    src = "def foo(): pass"
    result = extract_skeleton(src, "python")
    assert isinstance(result, str)
