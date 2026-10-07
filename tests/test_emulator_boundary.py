"""Applications access emulation exclusively through Core's public contract."""
import ast
from pathlib import Path


def test_no_backend_imports_or_private_adapter_access():
    root = Path(__file__).resolve().parents[1] / "pokesim"
    failures = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            if any(name.split(".")[0] in {"pyboy", "pyboy_rs", "pokesim_core_native"} for name in names):
                failures.append((path.name, node.lineno, "backend import"))
            if isinstance(node, ast.Attribute) and node.attr in {"_backend", "_machine", "_pb"}:
                failures.append((path.name, node.lineno, "private adapter access"))
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                if node.args[0].value in ("pyboy", "pyboy-rs", "pyboy_rs", "pokesim_core_native", "pokesim-core-native"):
                    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                    if name in {"version", "distribution", "import_module", "__import__"}:
                        failures.append((path.name, node.lineno, "backend lookup"))
    assert not failures, failures
