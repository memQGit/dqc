"""Copy the runnable demo notebooks into the docs site at build time.

The notebooks live in ``demo/`` so they stay runnable from a checkout, which
puts them outside MkDocs' ``docs_dir``. This script is run by
``mkdocs-gen-files``: it copies each notebook into a virtual ``demos/`` tree
where ``mkdocs-jupyter`` renders it as a page, along with any local asset each
notebook references from a markdown cell.

``mkdocs-jupyter`` publishes a notebook at ``demos/<name>/index.html``, so a
relative reference like ``outputs/execution.gif`` resolves against
``demos/<name>/``. Assets are therefore copied under that per-notebook prefix
rather than next to the notebook file.
"""

import json
import re
from pathlib import Path

import mkdocs_gen_files

root = Path(__file__).parent
demo_dir = root / "demo"

# Reading order shown in the site nav, mirroring demo/README.md.
NOTEBOOK_ORDER = [
    "demo.ipynb",
    "networks.ipynb",
    "comparing_partitioners.ipynb",
    "scheduling_and_hardware.ipynb",
    "visualization.ipynb",
]

# Markdown image/link targets and raw HTML src attributes.
_REFERENCE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)|src=\"([^\"]+)\"")


def _referenced_assets(notebook: dict[str, object]) -> set[str]:
    """Return relative asset paths referenced by a notebook's markdown.

    Args:
        notebook: Parsed notebook JSON.

    Returns:
        Relative paths, as written in the notebook source.
    """
    found: set[str] = set()
    cells = notebook.get("cells", [])
    if not isinstance(cells, list):
        return found
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", [])
        text = "".join(source) if isinstance(source, list) else str(source)
        for markdown_target, html_target in _REFERENCE.findall(text):
            target = markdown_target or html_target
            if target and not target.startswith(("http://", "https://", "/")):
                found.add(target)
    return found


for name in NOTEBOOK_ORDER:
    source_path = demo_dir / name
    if not source_path.is_file():
        continue

    with mkdocs_gen_files.open(f"demos/{name}", "wb") as fd:
        fd.write(source_path.read_bytes())
    mkdocs_gen_files.set_edit_path(
        f"demos/{name}", source_path.relative_to(root)
    )

    notebook = json.loads(source_path.read_text(encoding="utf-8"))
    for reference in _referenced_assets(notebook):
        asset = (demo_dir / reference).resolve()
        if not asset.is_file() or demo_dir.resolve() not in asset.parents:
            continue
        destination = f"demos/{source_path.stem}/{reference}"
        with mkdocs_gen_files.open(destination, "wb") as fd:
            fd.write(asset.read_bytes())
