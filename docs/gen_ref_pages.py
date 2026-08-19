# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate per-package API reference pages for the docs site.

This script is run by ``mkdocs-gen-files`` at build time. It walks the
``src/memq_dqc`` package, writes one Markdown stub per *package* containing a
single ``mkdocstrings`` autodoc directive, and emits a ``SUMMARY.md`` nav
consumed by ``mkdocs-literate-nav``. The generated files live in a virtual
``reference/`` tree and are never written to disk.

Only packages get a page, and a package documents exactly the names in its
``__all__``. A symbol is therefore in the API reference if and only if it is
re-exported from a package, which keeps the reference identical to the
public API contract and avoids documenting a symbol twice (once on its
defining module's page and again on the re-exporting package's page).
"""

import ast
from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

root = Path(__file__).parent.parent
src = root / "src"

#: Subpackages excluded from the API reference. The network builder is a
#: standalone local tool documented by its usage guide, not by its
#: internals, so its modules are not worth an autodoc page. The assets
#: package is a bundled data reference, not code worth autodoc'ing.
EXCLUDED_PACKAGES = {"network_builder", "assets"}

#: Subpackages whose entire ``__all__`` is re-exported by their parent
#: package. Their pages would be strict subsets of the parent's, so the
#: parent documents them instead. Listed explicitly rather than detected,
#: so that adding a name to a parent's ``__all__`` can never silently
#: delete a page.
ABSORBED_PACKAGES = {
    "memq_dqc.circuit.dag",
    "memq_dqc.partition.benchmark_random",
    "memq_dqc.partition.benchmark_static",
    "memq_dqc.partition.hypergraph",
    "memq_dqc.partition.interaction",
    "memq_dqc.partition.interaction_static",
}


def public_names(path: Path) -> list[str]:
    """Return the names listed in a module's ``__all__``.

    The module is parsed rather than imported, so generating the reference
    never triggers package import side effects.

    Args:
        path: Path to the ``__init__.py`` to inspect.

    Returns:
        The string entries of the module's ``__all__``, or an empty list
        when the module declares no ``__all__``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            continue
        return [
            e.value
            for e in node.value.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    return []


for path in sorted(src.rglob("__init__.py")):
    module_path = path.relative_to(src).with_suffix("")
    parts = tuple(module_path.parts[:-1])

    if not parts or EXCLUDED_PACKAGES & set(parts):
        continue

    identifier = ".".join(parts)
    if identifier in ABSORBED_PACKAGES:
        continue

    # A package with no ``__all__`` exports nothing publicly, so its page
    # would render as a bare docstring (e.g. ``memq_dqc.utils``, which
    # documents itself as private).
    if not public_names(path):
        continue

    doc_path = module_path.with_name("index.md")
    full_doc_path = Path("reference", doc_path)

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        fd.write(f"# `{identifier}`\n\n::: {identifier}\n")

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

with mkdocs_gen_files.open("reference/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
