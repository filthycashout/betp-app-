from __future__ import annotations

import ast
from pathlib import Path

from zero_trust_provenance import TOOL_SECURITY_POLICIES

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MCP_FILES = (
    BACKEND_ROOT / "mcp_server.py",
    BACKEND_ROOT / "mcp_v2_service.py",
)
MUTATING_HTTP_METHODS = {"post", "put", "patch", "delete"}
FORBIDDEN_EXECUTION_CALLS = {
    ("os", "system"),
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
}


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _attr_chain(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return tuple(reversed(parts))


def test_mcp_sources_are_syntax_valid():
    for path in MCP_FILES:
        _tree(path)


def test_standalone_mcp_does_not_use_mutating_http_verbs():
    tree = _tree(BACKEND_ROOT / "mcp_v2_service.py")
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)
        if len(chain) >= 2 and chain[-1].lower() in MUTATING_HTTP_METHODS:
            if chain[0] in {"SESSION", "requests"}:
                violations.append(".".join(chain))
    assert violations == []


def test_mcp_sources_do_not_spawn_commands_or_shells():
    violations: list[str] = []
    for path in MCP_FILES:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            chain = _attr_chain(node.func)
            if len(chain) >= 2 and (chain[-2], chain[-1]) in FORBIDDEN_EXECUTION_CALLS:
                violations.append(f"{path.name}:{'.'.join(chain)}")
    assert violations == []


def test_standalone_mcp_exposed_tool_functions_are_all_registered_in_policy():
    tree = _tree(BACKEND_ROOT / "mcp_v2_service.py")
    exposed: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and _attr_chain(decorator.func) == ("mcp", "tool"):
                exposed.add(node.name)
    assert exposed
    assert exposed == set(TOOL_SECURITY_POLICIES)


def test_embedded_mcp_declared_tools_are_registered_in_policy():
    tree = _tree(BACKEND_ROOT / "mcp_server.py")
    declared: set[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "TOOLS" for target in node.targets):
                literal = ast.literal_eval(node.value)
                declared = {str(item["name"]) for item in literal}
                break
    assert declared is not None
    assert declared
    # The embedded adapter intentionally exposes a strict subset of the
    # standalone research service, but every one must be governed.
    assert declared.issubset(TOOL_SECURITY_POLICIES)


def test_no_policy_entry_can_claim_external_mutation_without_code_review():
    assert all(policy.external_mutation is False for policy in TOOL_SECURITY_POLICIES.values())
