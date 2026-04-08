# Copilot Review Instructions for apfel-context

When performing a code review on this repository, apply these additional checks:

## AI-Generated Code Detection
Flag any of these patterns as potential issues:
- Imports that don't correspond to installed dependencies or Python stdlib
- Method calls on third-party libraries that may not exist (verify against actual API)
- Bare `except Exception` blocks that silently swallow errors
- Functions defined but never called anywhere in the codebase
- Docstrings that describe behavior different from what the code implements
- Return types in type hints that don't match all possible return paths

## Security-Specific Checks
This project writes user-controlled content to the filesystem. Pay extra attention to:
- Any file path constructed from user input
- Content sanitization before filesystem writes
- Path traversal attempts via event_type parameter in state_manager.py
- Null byte injection in content strings

## Context Window Safety
The apfel LLM has a 4,096 token context window. Flag any code that:
- Sends more than ~2,500 tokens of input to apfel without truncation
- Doesn't account for system prompt token cost in the budget
- Could produce unbounded output from apfel

## MCP Protocol Safety
This is an MCP server communicating via stdio. Flag:
- Any use of print() or sys.stdout.write() outside the MCP framework
- Any logging configured to write to stdout instead of stderr
- Any subprocess call that could interfere with stdin/stdout

## Test Coverage
When reviewing changes, verify that:
- New functions have corresponding test cases
- Edge cases (empty input, None, very large input) are tested
- Security-critical paths (path validation, input sanitization) have explicit tests
