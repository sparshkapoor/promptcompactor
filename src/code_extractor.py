"""
code_extractor.py — AST-based code skeleton extraction via Tree-sitter.

Converts source code to a compact skeleton: function/class signatures + docstrings,
bodies replaced with '...'. Typically achieves ~70% token reduction while preserving
all structural and semantic information needed for comprehension.

Falls back to returning the original source unchanged on any parse error, unsupported
language, or when the skeleton is not meaningfully shorter than the original.
"""

from pathlib import Path

# Map file extensions to Tree-sitter language names
EXT_TO_LANGUAGE: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "tsx",
    ".go":   "go",
    ".rs":   "rust",
    ".java": "java",
    ".c":    "c",
    ".cpp":  "cpp",
    ".h":    "c",
    ".hpp":  "cpp",
}

# Node types whose bodies we drop and replace with '...'
_FUNCTION_DEF_TYPES: dict[str, frozenset[str]] = {
    "python":     frozenset({"function_definition", "async_function_definition"}),
    "javascript": frozenset({"function_declaration", "function_expression",
                             "generator_function_declaration", "method_definition",
                             "arrow_function"}),
    "typescript": frozenset({"function_declaration", "function_expression",
                             "generator_function_declaration", "method_definition",
                             "arrow_function", "abstract_method_signature"}),
    "tsx":        frozenset({"function_declaration", "function_expression",
                             "method_definition", "arrow_function"}),
    "go":         frozenset({"function_declaration", "method_declaration"}),
    "rust":       frozenset({"function_item"}),
    "java":       frozenset({"method_declaration", "constructor_declaration"}),
    "c":          frozenset({"function_definition"}),
    "cpp":        frozenset({"function_definition"}),
}

# Node types we recurse into to find nested functions (class/struct/impl bodies)
_CLASS_DEF_TYPES: dict[str, frozenset[str]] = {
    "python":     frozenset({"class_definition"}),
    "javascript": frozenset({"class_declaration", "class_expression"}),
    "typescript": frozenset({"class_declaration", "class_expression",
                             "interface_declaration"}),
    "tsx":        frozenset({"class_declaration", "class_expression"}),
    "go":         frozenset({"type_declaration"}),
    "rust":       frozenset({"impl_item", "trait_item", "struct_item"}),
    "java":       frozenset({"class_declaration", "interface_declaration",
                             "enum_declaration"}),
    "c":          frozenset(),
    "cpp":        frozenset({"class_specifier", "struct_specifier"}),
}

# Node types that represent a function's body block
_BODY_TYPES: dict[str, frozenset[str]] = {
    "python":     frozenset({"block"}),
    "javascript": frozenset({"statement_block"}),
    "typescript": frozenset({"statement_block"}),
    "tsx":        frozenset({"statement_block"}),
    "go":         frozenset({"block"}),
    "rust":       frozenset({"block"}),
    "java":       frozenset({"block"}),
    "c":          frozenset({"compound_statement"}),
    "cpp":        frozenset({"compound_statement"}),
}


def language_for_path(filepath: str) -> str | None:
    """Return the Tree-sitter language name for a file path, or None if unsupported."""
    return EXT_TO_LANGUAGE.get(Path(filepath).suffix.lower())


def extract_skeleton(source: str, language: str) -> str:
    """
    Return a skeleton of source: signatures + docstrings, bodies replaced with '...'.

    Returns the original source unchanged when:
    - tree-sitter-languages is not installed
    - the language is not in the supported set
    - parsing raises any exception
    - the skeleton is not at least 10% shorter than the original
    """
    if not source or not source.strip():
        return source

    try:
        from tree_sitter_languages import get_parser  # type: ignore
        parser = get_parser(language)
    except Exception:
        return source

    try:
        src_bytes = source.encode("utf-8")
        tree = parser.parse(src_bytes)
        lines = source.splitlines()

        fn_types   = _FUNCTION_DEF_TYPES.get(language, frozenset())
        cls_types  = _CLASS_DEF_TYPES.get(language, frozenset())
        body_types = _BODY_TYPES.get(language, frozenset())

        # Collect (start_line, end_line) ranges to replace with '...' (0-indexed, inclusive)
        drops: list[tuple[int, int]] = []

        def _first_docstring_end_row(block_node) -> int | None:
            """Return the last line of the first docstring in a Python block, or None."""
            for child in block_node.children:
                if child.type == "expression_statement":
                    for gc in child.children:
                        if gc.type in ("string", "concatenated_string"):
                            return gc.end_point[0]
                    break
                if child.type not in ("comment", "newline"):
                    break
            return None

        def walk(node) -> None:
            if node.type in fn_types:
                for child in node.children:
                    if child.type in body_types:
                        body_start = child.start_point[0]
                        body_end   = child.end_point[0]

                        if language == "python":
                            doc_end    = _first_docstring_end_row(child)
                            drop_start = (doc_end + 1) if doc_end is not None else body_start
                            drop_end   = body_end
                        else:
                            # Brace-delimited: drop interior, keep opening/closing brace lines
                            drop_start = body_start + 1
                            drop_end   = body_end - 1

                        if drop_start <= drop_end:
                            drops.append((drop_start, drop_end))
                        break
                return  # Don't recurse into function bodies

            if node.type in cls_types:
                # Recurse into class/struct bodies to surface nested definitions
                for child in node.children:
                    walk(child)
                return

            for child in node.children:
                walk(child)

        walk(tree.root_node)

        if not drops:
            return source

        # Merge overlapping/adjacent ranges
        drops.sort()
        merged: list[list[int]] = []
        for start, end in drops:
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

        # Build output, replacing each dropped range with a single indented '...' line
        result: list[str] = []
        i = 0
        di = 0
        while i < len(lines):
            # Advance past any ranges that are entirely behind us
            while di < len(merged) and i > merged[di][1]:
                di += 1

            if di < len(merged) and merged[di][0] <= i <= merged[di][1]:
                if i == merged[di][0]:
                    raw    = lines[i]
                    indent = len(raw) - len(raw.lstrip())
                    result.append(" " * indent + "...")
                i = merged[di][1] + 1
                di += 1
            else:
                result.append(lines[i])
                i += 1

        skeleton = "\n".join(result)
        # Only return the skeleton when it meaningfully reduces size
        if len(skeleton) < len(source) * 0.9:
            return skeleton
        return source

    except Exception:
        return source
