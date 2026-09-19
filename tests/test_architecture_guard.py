import ast
from pathlib import Path

from doxagon.architecture import (
    CONVERTED_MODULES,
    FORBIDDEN_DISCOVERY_CALLS,
    FORBIDDEN_LEGACY_IMPORTS,
    LEGACY_ADAPTER_MODULE,
    SANCTIONED_CWD_CALLSITES,
)


ROOT = Path(__file__).parents[1]


def _module_path(module: str) -> Path:
    module_path = ROOT / "src" / Path(*module.split("."))
    file_path = module_path.with_suffix(".py")
    return file_path if file_path.is_file() else module_path / "__init__.py"


def _canonical_reference(node: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        value = _canonical_reference(node.value, aliases)
        if value is not None:
            return f"{value}.{node.attr}"
    return None


def _imports_and_calls(path: Path, module: str) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    aliases: dict[str, str] = {}
    package = module.rsplit(".", maxsplit=1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                aliases[alias.asname or alias.name.split(".", maxsplit=1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            parent = package.split(".")
            if node.level:
                parent = parent[: len(parent) - (node.level - 1)]
                module_name = ".".join(part for part in (*parent, node.module or "") if part)
            else:
                module_name = node.module or ""
            if module_name:
                imports.add(module_name)
            for alias in node.names:
                member = f"{module_name}.{alias.name}" if module_name else alias.name
                imports.add(member)
                aliases[alias.asname or alias.name] = "Path" if member == "pathlib.Path" else member
        elif isinstance(node, ast.Call):
            reference = _canonical_reference(node.func, aliases)
            if reference is not None:
                calls.add(reference.replace("pathlib.Path.", "Path."))
            if reference in {"Path", "pathlib.Path"} and any(
                isinstance(argument, ast.Name) and argument.id == "__file__" for argument in node.args
            ):
                calls.add("Path.__file__")
    return imports, calls


def _path_cwd_call_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        function.name
        for function in tree.body
        if isinstance(function, ast.FunctionDef)
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and _canonical_reference(call.func, {}) == "Path.cwd"
    }


def _guard_violations(path: Path, module: str) -> set[str]:
    imports, calls = _imports_and_calls(path, module)
    forbidden_calls = calls.intersection(FORBIDDEN_DISCOVERY_CALLS)
    if SANCTIONED_CWD_CALLSITES.get(module):
        forbidden_calls.discard("Path.cwd")
    return imports.intersection(FORBIDDEN_LEGACY_IMPORTS) | forbidden_calls


def test_converted_modules_do_not_discover_checkout_or_import_legacy_globals() -> None:
    for module in CONVERTED_MODULES:
        path = _module_path(module)
        assert not _guard_violations(path, module)
        assert _path_cwd_call_functions(path) == SANCTIONED_CWD_CALLSITES.get(module, frozenset())


def test_guard_resolves_import_from_members_aliases_and_call_forms(tmp_path: Path) -> None:
    source = tmp_path / "converted.py"
    source.write_text(
        "\n".join(
            (
                "from doxagon import config",
                "from doxagon.compat import legacy",
                "from os import getcwd as current_directory",
                "from pathlib import Path as VaultPath",
                "current_directory()",
                "VaultPath.cwd()",
            )
        ),
        encoding="utf-8",
    )

    imports, calls = _imports_and_calls(source, "doxagon.converted")

    assert {"doxagon.config", "doxagon.compat.legacy"}.issubset(imports)
    assert {"os.getcwd", "Path.cwd"}.issubset(calls)


def test_guard_rejects_path_file_checkout_discovery_in_converted_module(tmp_path: Path) -> None:
    source = tmp_path / "converted.py"
    source.write_text(
        "from pathlib import Path as VaultPath\nroot = VaultPath(__file__).parents[1]\n",
        encoding="utf-8",
    )

    assert _guard_violations(source, "doxagon.converted") == {"Path.__file__"}


def test_legacy_adapter_is_the_explicitly_bounded_non_converted_seam() -> None:
    adapter = _module_path(LEGACY_ADAPTER_MODULE)

    assert adapter.is_file()
    assert LEGACY_ADAPTER_MODULE not in CONVERTED_MODULES
