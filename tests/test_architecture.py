"""Architecture rules, checked statically (no services needed).

1. Package boundaries: which graph_agent packages may import which.
2. The generic project (core, frame, harness, service) contains no domain vocabulary.
3. Packs do not import each other, and the fire simulator imports nothing outside itself.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src" / "graph_agent"
PACKAGE = "graph_agent"

# package -> packages it may import (itself is always allowed). The main project is generic: it
# knows no pack. Packs (Ring Fire, life, Hualien) sit on top of it, and only the service lists them.
ALLOWED = {
    "core": set(),
    "stores": {"core"},
    "harness": {"core"},  # the model client, the turn loop, the run trace
    "frame": {"core", "harness"},
    "packs": {"core", "stores", "harness", "frame"},
    "service": {"core", "stores", "harness", "frame", "packs"},
}

# Words that must never appear in the core. "field" is left out on purpose:
# pydantic's Field would be a false positive.
DOMAIN_WORDS = ["fire", "water", "imposter", "burn", "quake", "earthquake", "hualien"]


def imported_packages(source: str, module: str) -> set[str]:
    """Top-level graph_agent subpackages imported by `source`.

    `module` is the dotted name of the file being checked, for example
    "graph_agent.core.model", so relative imports can be resolved.
    """
    found: set[str] = set()
    parts = module.split(".")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = parts[: len(parts) - node.level]
                names = [".".join(base + ([node.module] if node.module else []))]
                # "from .. import core" imports graph_agent.core
                names += [".".join([*names[0].split("."), a.name]) for a in node.names]
            else:
                names = [node.module or ""]
        else:
            continue
        for name in names:
            segments = name.split(".")
            if len(segments) >= 2 and segments[0] == PACKAGE:
                found.add(segments[1])
    return found


def test_checker_detects_absolute_and_relative_imports():
    assert imported_packages("import graph_agent.sim.engine", "graph_agent.core.x") == {"sim"}
    assert imported_packages("from graph_agent.stores import a", "graph_agent.core.x") == {"stores"}
    assert imported_packages("from ..sim import engine", "graph_agent.core.x") == {"sim"}
    assert imported_packages("from .. import sim", "graph_agent.core.x") == {"sim"}
    assert imported_packages("from . import other", "graph_agent.core.x") == {"core"}
    assert imported_packages("import json, os", "graph_agent.core.x") == set()


def _python_files(package: str):
    return sorted((ROOT / package).rglob("*.py"))


def test_package_boundaries():
    violations = []
    for package, allowed in ALLOWED.items():
        for path in _python_files(package):
            module = ".".join(path.relative_to(ROOT.parent).with_suffix("").parts)
            used = imported_packages(path.read_text(), module) - {package}
            bad = used - allowed
            if bad:
                violations.append(f"{path.relative_to(ROOT.parent)} imports {sorted(bad)}")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("package", ["core", "frame", "harness", "service"])
def test_the_main_project_has_no_domain_vocabulary(package):
    pattern = re.compile(r"\b(" + "|".join(DOMAIN_WORDS) + r")\b", re.IGNORECASE)
    hits = []
    for path in _python_files(package):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            match = pattern.search(line)
            if match:
                hits.append(f"{path.relative_to(ROOT.parent)}:{lineno}: '{match.group(0)}'")
    assert not hits, "\n".join(hits)


PACKS_ROOT = ROOT / "packs"


def test_packs_do_not_import_each_other():
    violations = []
    for pack in [d.name for d in PACKS_ROOT.iterdir() if d.is_dir() and d.name != "__pycache__"]:
        for path in sorted((PACKS_ROOT / pack).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom) and not node.level
                    else []
                )
                for name in names:
                    parts = name.split(".")
                    if parts[:2] == [PACKAGE, "packs"] and len(parts) > 2 and parts[2] != pack:
                        violations.append(f"{path.relative_to(ROOT.parent)} imports {name}")
    assert not violations, "\n".join(violations)


def test_the_fire_simulator_imports_nothing_outside_itself():
    sim = PACKS_ROOT / "ringfire" / "sim"
    violations = []
    for path in sorted(sim.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (
                node.level > 1 or (node.module or "").startswith(PACKAGE)
            ):
                violations.append(f"{path.relative_to(ROOT.parent)}: {node.module}")
    assert not violations, "\n".join(violations)
