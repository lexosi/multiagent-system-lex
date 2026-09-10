"""Static guard: every third-party import in the tree is declared in a manifest.

Walks *every* ``*.py`` under the repo (``tests/`` included), collects the
module-level third-party imports via the AST, and asserts each one is declared
in either ``requirements.txt`` (runtime) or ``requirements-dev.txt`` (dev). This
is the rot-guard for H-3: a new dependency added to any module without a manifest
entry turns this test red.

The manifests are a *reference*, not an install contract -- this repo is not
installable by design (see their headers). The test only checks that the set of
imported third-party packages is a subset of the declared set; it does not
install anything or assert versions.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {".venv", ".git", "__pycache__"}

# import name -> pip distribution name, only where they differ.
IMPORT_TO_PKG = {"dotenv": "python-dotenv"}


def _normalize(name: str) -> str:
    """Canonicalize a package/import name for comparison (PEP 503-ish)."""
    return name.strip().lower().replace("_", "-")


def _iter_py_files() -> list[Path]:
    return [
        p
        for p in REPO_ROOT.rglob("*.py")
        if not EXCLUDED_DIRS.intersection(p.parts)
    ]


def _local_module_names() -> set[str]:
    """Top-level names importable from within the repo (first-party)."""
    return {p.stem for p in _iter_py_files()}


def _third_party_imports() -> dict[str, list[str]]:
    """Map each third-party top-level import name -> files that import it."""
    stdlib = set(sys.stdlib_module_names)
    local = _local_module_names()
    found: dict[str, list[str]] = {}
    for py in _iter_py_files():
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in stdlib or name in local:
                    continue
                found.setdefault(name, []).append(
                    str(py.relative_to(REPO_ROOT)).replace("\\", "/")
                )
    return found


def _manifest_packages() -> set[str]:
    """Union of declared packages across both requirement manifests."""
    packages: set[str] = set()
    for fname in ("requirements.txt", "requirements-dev.txt"):
        path = REPO_ROOT / fname
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            # strip extras, version specifiers, environment markers
            token = line.split(";", 1)[0]
            token = token.split("[", 1)[0]
            for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "="):
                token = token.split(sep, 1)[0]
            if token.strip():
                packages.add(_normalize(token))
    return packages


class TestDependencyManifest:
    def test_at_least_one_manifest_exists(self) -> None:
        runtime = REPO_ROOT / "requirements.txt"
        dev = REPO_ROOT / "requirements-dev.txt"
        assert runtime.exists() or dev.exists(), (
            "no requirements.txt / requirements-dev.txt found -- "
            "third-party imports are undeclared"
        )

    def test_every_third_party_import_is_declared(self) -> None:
        manifest = _manifest_packages()
        undeclared: dict[str, list[str]] = {}
        for imp, files in _third_party_imports().items():
            pkg = _normalize(IMPORT_TO_PKG.get(imp, imp))
            if pkg not in manifest:
                undeclared[imp] = files
        assert not undeclared, (
            "third-party imports missing from requirements*.txt: "
            + ", ".join(f"{imp} ({files[0]})" for imp, files in sorted(undeclared.items()))
        )
