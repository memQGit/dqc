"""SVG document helpers for visualization outputs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which
from subprocess import run
from xml.sax.saxutils import escape


@dataclass(frozen=True, slots=True)
class SvgDocument:
    """A standalone SVG visualization artifact.

    Args:
        width: Canvas width in pixels.
        height: Canvas height in pixels.
        svg: Full SVG markup for the document.
    """

    width: int
    height: int
    svg: str

    def write_svg(self, path: str | Path) -> Path:
        """Write the SVG markup to disk.

        Args:
            path: Destination SVG filepath.

        Returns:
            The resolved output path.
        """
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.svg, encoding="utf-8")
        return output_path

    def to_html(self, *, title: str = "Visualization") -> str:
        """Wrap the SVG in a lightweight interactive HTML viewer.

        Args:
            title: Viewer title shown above the canvas.

        Returns:
            A standalone HTML document with pan and zoom controls.
        """
        svg_markup = self.svg.replace(
            "<svg ",
            '<svg class="viewer__svg" ',
            1,
        )
        escaped_title = escape(title)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --panel: #ffffff;
      --panel-border: #d8deea;
      --surface: #f6f3ff;
      --surface-accent: rgba(72, 1, 176, 0.06);
      --text: #102a43;
      --muted: #52606d;
      --accent: #4801b0;
      --accent-bright: #d702fe;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, var(--surface-accent), transparent 32%),
        linear-gradient(180deg, #fcfbff 0%, #f6f7fb 100%);
    }}
    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 16px;
      padding: 18px;
    }}
    .toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      border: 1px solid var(--panel-border);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.9);
      backdrop-filter: blur(12px);
      box-shadow: 0 14px 40px rgba(16, 42, 67, 0.08);
    }}
    .title-block h1 {{
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
    }}
    .title-block p {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .controls button {{
      border: 1px solid var(--panel-border);
      border-radius: 10px;
      background: var(--panel);
      color: var(--text);
      padding: 8px 12px;
      font: inherit;
      cursor: pointer;
    }}
    .controls button:hover {{
      border-color: var(--accent-bright);
      color: var(--accent);
    }}
    .viewport {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--panel-border);
      border-radius: 18px;
      background:
        linear-gradient(90deg, rgba(72, 1, 176, 0.05) 1px, transparent 1px),
        linear-gradient(rgba(72, 1, 176, 0.05) 1px, transparent 1px),
        linear-gradient(180deg, #fffefe 0%, #f5f3ff 100%);
      background-size: 28px 28px, 28px 28px, 100% 100%;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
      min-height: 640px;
      touch-action: none;
      cursor: grab;
    }}
    .viewport.is-dragging {{
      cursor: grabbing;
    }}
    .canvas {{
      position: absolute;
      left: 0;
      top: 0;
      transform-origin: 0 0;
      will-change: transform;
    }}
    .viewer__svg {{
      display: block;
      overflow: visible;
      box-shadow: 0 18px 44px rgba(16, 42, 67, 0.12);
      border-radius: 16px;
    }}
    @media (max-width: 900px) {{
      .toolbar {{
        align-items: flex-start;
        flex-direction: column;
      }}
      .viewport {{
        min-height: 520px;
      }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <header class="toolbar">
      <div class="title-block">
        <h1>{escaped_title}</h1>
        <p>Drag to pan, scroll to zoom, or use the fit/reset controls.</p>
      </div>
      <div class="controls">
        <button type="button" data-action="zoom-out">-</button>
        <button type="button" data-action="zoom-in">+</button>
        <button type="button" data-action="fit">Fit</button>
        <button type="button" data-action="reset">100%</button>
      </div>
    </header>
    <main class="viewport">
      <div class="canvas">
        {svg_markup}
      </div>
    </main>
  </div>
  <script>
    const viewport = document.querySelector(".viewport");
    const canvas = document.querySelector(".canvas");
    const baseWidth = {self.width};
    const baseHeight = {self.height};
    const state = {{
      scale: 1,
      x: 0,
      y: 0,
      minScale: 0.08,
      maxScale: 8,
      pointerId: null,
      originX: 0,
      originY: 0,
    }};

    function applyTransform() {{
      canvas.style.transform =
        `translate(${{state.x}}px, ${{state.y}}px) scale(${{state.scale}})`;
    }}

    function fitToViewport() {{
      const padding = 32;
      const scale = Math.min(
        (viewport.clientWidth - padding * 2) / baseWidth,
        (viewport.clientHeight - padding * 2) / baseHeight,
      );
      state.scale = Math.max(
        state.minScale,
        Math.min(state.maxScale, scale || 1),
      );
      state.x = (viewport.clientWidth - baseWidth * state.scale) / 2;
      state.y = (viewport.clientHeight - baseHeight * state.scale) / 2;
      applyTransform();
    }}

    function resetZoom() {{
      state.scale = 1;
      state.x = 24;
      state.y = 24;
      applyTransform();
    }}

    function zoomAt(clientX, clientY, deltaScale) {{
      const rect = viewport.getBoundingClientRect();
      const px = clientX - rect.left;
      const py = clientY - rect.top;
      const worldX = (px - state.x) / state.scale;
      const worldY = (py - state.y) / state.scale;
      const nextScale = Math.max(
        state.minScale,
        Math.min(state.maxScale, state.scale * deltaScale),
      );
      state.x = px - worldX * nextScale;
      state.y = py - worldY * nextScale;
      state.scale = nextScale;
      applyTransform();
    }}

    viewport.addEventListener("wheel", (event) => {{
      event.preventDefault();
      const deltaScale = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomAt(event.clientX, event.clientY, deltaScale);
    }}, {{ passive: false }});

    viewport.addEventListener("pointerdown", (event) => {{
      state.pointerId = event.pointerId;
      state.originX = event.clientX - state.x;
      state.originY = event.clientY - state.y;
      viewport.classList.add("is-dragging");
      viewport.setPointerCapture(event.pointerId);
    }});

    viewport.addEventListener("pointermove", (event) => {{
      if (state.pointerId !== event.pointerId) {{
        return;
      }}
      state.x = event.clientX - state.originX;
      state.y = event.clientY - state.originY;
      applyTransform();
    }});

    function releasePointer(event) {{
      if (state.pointerId !== event.pointerId) {{
        return;
      }}
      state.pointerId = null;
      viewport.classList.remove("is-dragging");
    }}

    viewport.addEventListener("pointerup", releasePointer);
    viewport.addEventListener("pointercancel", releasePointer);
    viewport.addEventListener("dblclick", fitToViewport);
    window.addEventListener("resize", fitToViewport);

    document
      .querySelector('[data-action="zoom-in"]')
      .addEventListener("click", () => {{
        const rect = viewport.getBoundingClientRect();
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 1.16);
      }});
    document
      .querySelector('[data-action="zoom-out"]')
      .addEventListener("click", () => {{
        const rect = viewport.getBoundingClientRect();
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, 1 / 1.16);
      }});
    document
      .querySelector('[data-action="fit"]')
      .addEventListener("click", fitToViewport);
    document
      .querySelector('[data-action="reset"]')
      .addEventListener("click", resetZoom);

    fitToViewport();
  </script>
</body>
</html>
"""

    def write_html(
        self, path: str | Path, *, title: str = "Visualization"
    ) -> Path:
        """Write the interactive HTML viewer to disk.

        Args:
            path: Destination HTML filepath.
            title: Viewer title shown above the canvas.

        Returns:
            The resolved output path.
        """
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.to_html(title=title), encoding="utf-8")
        return output_path

    def write_png(self, path: str | Path) -> Path:
        """Rasterize the SVG document to PNG.

        Args:
            path: Destination PNG filepath.

        Returns:
            The resolved output path.

        Raises:
            RuntimeError: If ``rsvg-convert`` is unavailable or conversion
                fails.
        """
        converter = which("rsvg-convert")
        if converter is None:
            raise RuntimeError("rsvg-convert is required to write PNG output.")

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = run(
            [
                converter,
                "--format",
                "png",
                "--output",
                str(output_path),
            ],
            input=self.svg,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "rsvg-convert failed with exit code "
                f"{result.returncode}: {result.stderr.strip()}"
            )
        return output_path


@dataclass(frozen=True, slots=True)
class SvgDashboardPanel:
    """A single visualization card inside an HTML dashboard.

    Args:
        title: Card heading shown above the embedded SVG.
        document: SVG document rendered inside the card.
        description: Optional supporting text shown under the title.
    """

    title: str
    document: SvgDocument
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SvgDashboardSection:
    """A grouped dashboard section containing one or more visualization cards.

    Args:
        title: Section heading shown in the dashboard.
        panels: Visualization cards rendered within the section.
        description: Optional supporting text shown under the heading.
    """

    title: str
    panels: Sequence[SvgDashboardPanel]
    description: str | None = None


def build_svg_dashboard_html(
    sections: Sequence[SvgDashboardSection],
    *,
    title: str = "Visualization Dashboard",
) -> str:
    """Build a standalone HTML dashboard for multiple SVG visualizations.

    Args:
        sections: Ordered dashboard sections to render.
        title: Document title shown at the top of the dashboard.

    Returns:
        A standalone HTML document with all provided visualizations embedded.
    """
    escaped_title = escape(title)
    nav_links = "\n".join(
        (
            '<a class="dashboard__nav-link" '
            f'href="#{_slugify(section.title)}">{escape(section.title)}</a>'
        )
        for section in sections
    )
    sections_markup = "\n".join(
        _dashboard_section_markup(section) for section in sections
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f3f7fb;
      --page-accent: #e3eefb;
      --panel: rgba(255, 255, 255, 0.92);
      --panel-border: #cad7e6;
      --text: #102a43;
      --muted: #52606d;
      --accent: #0f766e;
      --accent-soft: rgba(15, 118, 110, 0.10);
      --shadow: 0 20px 48px rgba(16, 42, 67, 0.10);
    }}
    * {{
      box-sizing: border-box;
    }}
    html {{
      scroll-behavior: smooth;
    }}
    body {{
      margin: 0;
      color: var(--text);
      font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
      background:
        radial-gradient(circle at top right, var(--page-accent), transparent 28%),
        linear-gradient(180deg, #fbfdff 0%, var(--page) 100%);
    }}
    .dashboard {{
      width: min(1500px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }}
    .dashboard__hero {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: grid;
      gap: 14px;
      margin-bottom: 20px;
      padding: 18px 20px;
      border: 1px solid var(--panel-border);
      border-radius: 20px;
      background: rgba(248, 251, 255, 0.88);
      backdrop-filter: blur(14px);
      box-shadow: var(--shadow);
    }}
    .dashboard__hero h1 {{
      margin: 0;
      font-size: clamp(28px, 4vw, 42px);
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    .dashboard__hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .dashboard__nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .dashboard__nav-link {{
      border: 1px solid var(--panel-border);
      border-radius: 999px;
      padding: 7px 12px;
      color: var(--text);
      text-decoration: none;
      background: #ffffff;
    }}
    .dashboard__nav-link:hover {{
      border-color: var(--accent);
      color: var(--accent);
      background: var(--accent-soft);
    }}
    .dashboard__section {{
      display: grid;
      gap: 14px;
      margin-bottom: 28px;
      padding: 0;
      border: none;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
    }}
    .dashboard__section-header {{
      display: grid;
      gap: 6px;
    }}
    .dashboard__section-header h2 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.1;
    }}
    .dashboard__section-header p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .dashboard__featured {{
      display: grid;
    }}
    .dashboard__grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .dashboard-card {{
      display: grid;
      gap: 12px;
      padding: 0;
      border: none;
      border-radius: 0;
      background: transparent;
      min-width: 0;
    }}
    .dashboard-card--featured {{
      gap: 14px;
      padding: 18px;
    }}
    .dashboard-card__header {{
      display: grid;
      gap: 4px;
    }}
    .dashboard-card--featured .dashboard-card__header h3 {{
      font-size: 20px;
    }}
    .dashboard-card__header h3 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.15;
    }}
    .dashboard-card__header p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .dashboard-card__viewport {{
      overflow: hidden;
      width: 100%;
      padding: 10px;
      border: none;
      border-radius: 14px;
      background: #ffffff;
      box-shadow: 0 10px 24px rgba(16, 42, 67, 0.08);
      display: block;
      cursor: zoom-in;
      appearance: none;
      text-align: left;
    }}
    .dashboard-card__svg {{
      display: block;
      width: 100%;
      max-width: 100%;
      height: auto;
      box-shadow: none;
    }}
    .dashboard-card__hint {{
      color: var(--muted);
      font-size: 12px;
    }}
    .dashboard-modal {{
      position: fixed;
      inset: 0;
      z-index: 100;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(16, 42, 67, 0.68);
      backdrop-filter: blur(8px);
    }}
    .dashboard-modal[hidden] {{
      display: none;
    }}
    .dashboard-modal__sheet {{
      width: min(1440px, 100%);
      max-height: calc(100vh - 40px);
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 12px;
      padding: 16px;
      border-radius: 18px;
      background: #f8fbff;
      box-shadow: 0 24px 60px rgba(16, 42, 67, 0.28);
    }}
    .dashboard-modal__header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }}
    .dashboard-modal__title {{
      margin: 0;
      font-size: 18px;
      line-height: 1.15;
    }}
    .dashboard-modal__description {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .dashboard-modal__close {{
      border: 1px solid var(--panel-border);
      border-radius: 999px;
      padding: 8px 12px;
      background: #ffffff;
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }}
    .dashboard-modal__viewport {{
      overflow: auto;
      padding: 12px;
      border-radius: 14px;
      background: #ffffff;
    }}
    .dashboard-modal__viewport svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    @media (max-width: 1180px) {{
      .dashboard__grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 720px) {{
      .dashboard {{
        width: min(100vw - 20px, 1500px);
        padding-top: 10px;
      }}
      .dashboard__hero {{
        position: static;
      }}
      .dashboard__section {{
        padding: 16px;
      }}
    }}
  </style>
</head>
<body>
  <main class="dashboard">
    <header class="dashboard__hero">
      <div>
        <h1>{escaped_title}</h1>
        <p>One standalone HTML view for every generated visualization.</p>
      </div>
      <nav class="dashboard__nav">
        {nav_links}
      </nav>
    </header>
    {sections_markup}
  </main>
  <div class="dashboard-modal" hidden>
    <div class="dashboard-modal__sheet" role="dialog" aria-modal="true">
      <div class="dashboard-modal__header">
        <div>
          <h2 class="dashboard-modal__title"></h2>
          <p class="dashboard-modal__description"></p>
        </div>
        <button class="dashboard-modal__close" type="button">Close</button>
      </div>
      <div class="dashboard-modal__viewport"></div>
    </div>
  </div>
  <script>
    const svgNamespace = "http://www.w3.org/2000/svg";

    function wrapSvgContent(svg) {{
      const background = svg.querySelector(":scope > .svg-document__background");
      if (background) {{
        background.remove();
      }}
      let group = svg.querySelector(":scope > g.dashboard-crop-group");
      if (group) {{
        return group;
      }}
      group = document.createElementNS(svgNamespace, "g");
      group.setAttribute("class", "dashboard-crop-group");
      for (const child of [...svg.childNodes]) {{
        if (child === group) {{
          continue;
        }}
        group.appendChild(child);
      }}
      svg.appendChild(group);
      return group;
    }}

    function cropSvg(svg) {{
      const group = wrapSvgContent(svg);
      const bbox = group.getBBox();
      const padX = Math.max(12, bbox.width * 0.03);
      const padY = Math.max(12, bbox.height * 0.05);
      svg.setAttribute(
        "viewBox",
        `${{bbox.x - padX}} ${{bbox.y - padY}} `
          + `${{bbox.width + padX * 2}} ${{bbox.height + padY * 2}}`,
      );
      svg.removeAttribute("width");
      svg.removeAttribute("height");
      svg.dataset.cropped = "true";
    }}

    const modal = document.querySelector(".dashboard-modal");
    const modalTitle = document.querySelector(".dashboard-modal__title");
    const modalDescription = document.querySelector(
      ".dashboard-modal__description",
    );
    const modalViewport = document.querySelector(".dashboard-modal__viewport");
    const modalClose = document.querySelector(".dashboard-modal__close");

    function openModal(viewport) {{
      const title = viewport.dataset.panelTitle || "Visualization";
      const description = viewport.dataset.panelDescription || "";
      const svg = viewport.querySelector("svg");
      if (!svg) {{
        return;
      }}
      modalTitle.textContent = title;
      modalDescription.textContent = description;
      modalViewport.replaceChildren(svg.cloneNode(true));
      modal.hidden = false;
      document.body.style.overflow = "hidden";
    }}

    function closeModal() {{
      modal.hidden = true;
      modalViewport.replaceChildren();
      document.body.style.overflow = "";
    }}

    for (const svg of document.querySelectorAll(".dashboard-card__svg")) {{
      cropSvg(svg);
    }}

    for (const viewport of document.querySelectorAll(".dashboard-card__viewport")) {{
      viewport.addEventListener("click", () => openModal(viewport));
    }}

    modalClose.addEventListener("click", closeModal);
    modal.addEventListener("click", (event) => {{
      if (event.target === modal) {{
        closeModal();
      }}
    }});
    window.addEventListener("keydown", (event) => {{
      if (event.key === "Escape" && !modal.hidden) {{
        closeModal();
      }}
    }});
  </script>
</body>
</html>
"""


def write_svg_dashboard_html(
    path: str | Path,
    sections: Sequence[SvgDashboardSection],
    *,
    title: str = "Visualization Dashboard",
) -> Path:
    """Write a standalone SVG dashboard HTML document to disk.

    Args:
        path: Destination HTML filepath.
        sections: Ordered dashboard sections to render.
        title: Document title shown at the top of the dashboard.

    Returns:
        The resolved output path.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_svg_dashboard_html(sections, title=title),
        encoding="utf-8",
    )
    return output_path


@dataclass(slots=True)
class SvgCanvas:
    """Minimal SVG builder for programmatic diagram generation.

    Args:
        width: Canvas width in pixels.
        height: Canvas height in pixels.
        background: Background fill color for the full document.
    """

    width: int
    height: int
    background: str = "#fcfcfd"
    _elements: list[str] = field(default_factory=list)

    def rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        fill: str = "none",
        stroke: str = "none",
        stroke_width: float = 0.0,
        rx: float = 0.0,
        opacity: float = 1.0,
        dasharray: str | None = None,
    ) -> None:
        """Add a rectangle element to the SVG."""
        self._elements.append(
            _tag(
                "rect",
                x=_fmt(x),
                y=_fmt(y),
                width=_fmt(width),
                height=_fmt(height),
                fill=fill,
                stroke=stroke,
                **_maybe(
                    stroke_width=stroke_width,
                    rx=rx,
                    opacity=opacity,
                    dasharray=dasharray,
                ),
            )
        )

    def line(
        self,
        *,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        stroke: str,
        stroke_width: float = 1.0,
        opacity: float = 1.0,
        dasharray: str | None = None,
        linecap: str = "round",
    ) -> None:
        """Add a straight line element to the SVG."""
        self._elements.append(
            _tag(
                "line",
                x1=_fmt(x1),
                y1=_fmt(y1),
                x2=_fmt(x2),
                y2=_fmt(y2),
                stroke=stroke,
                **_maybe(
                    stroke_width=stroke_width,
                    opacity=opacity,
                    dasharray=dasharray,
                    linecap=linecap,
                ),
            )
        )

    def circle(
        self,
        *,
        cx: float,
        cy: float,
        r: float,
        fill: str,
        stroke: str = "none",
        stroke_width: float = 0.0,
    ) -> None:
        """Add a circle element to the SVG."""
        self._elements.append(
            _tag(
                "circle",
                cx=_fmt(cx),
                cy=_fmt(cy),
                r=_fmt(r),
                fill=fill,
                stroke=stroke,
                **_maybe(stroke_width=stroke_width),
            )
        )

    def path(
        self,
        *,
        d: str,
        fill: str = "none",
        stroke: str = "none",
        stroke_width: float = 0.0,
        opacity: float = 1.0,
        dasharray: str | None = None,
        linecap: str = "round",
        linejoin: str = "round",
    ) -> None:
        """Add a path element to the SVG."""
        self._elements.append(
            _tag(
                "path",
                d=d,
                fill=fill,
                stroke=stroke,
                **_maybe(
                    stroke_width=stroke_width,
                    opacity=opacity,
                    dasharray=dasharray,
                    linecap=linecap,
                    linejoin=linejoin,
                ),
            )
        )

    def text(
        self,
        *,
        x: float,
        y: float,
        text: str,
        fill: str = "#102a43",
        font_size: float = 14.0,
        font_family: str = "'IBM Plex Sans', 'Helvetica Neue', sans-serif",
        font_weight: str = "400",
        anchor: str = "start",
    ) -> None:
        """Add a text element to the SVG."""
        attributes = _attrs(
            x=_fmt(x),
            y=_fmt(y),
            fill=fill,
            font_size=font_size,
            font_family=font_family,
            font_weight=font_weight,
            text_anchor=anchor,
        )
        self._elements.append(f"<text {attributes}>{escape(text)}</text>")

    def text_spans(
        self,
        *,
        x: float,
        y: float,
        spans: list[tuple[str, dict[str, str | float] | None]],
        fill: str = "#102a43",
        font_size: float = 14.0,
        font_family: str = "'IBM Plex Sans', 'Helvetica Neue', sans-serif",
        font_weight: str = "400",
        anchor: str = "start",
    ) -> None:
        """Add a text element with one or more ``tspan`` children."""
        text_attributes = _attrs(
            x=_fmt(x),
            y=_fmt(y),
            fill=fill,
            font_size=font_size,
            font_family=font_family,
            font_weight=font_weight,
            text_anchor=anchor,
        )
        children: list[str] = []
        for text, attributes in spans:
            span_attributes = _attrs(**(attributes or {}))
            children.append(
                f"<tspan {span_attributes}>{escape(text)}</tspan>"
                if span_attributes
                else f"<tspan>{escape(text)}</tspan>"
            )
        self._elements.append(
            f"<text {text_attributes}>{''.join(children)}</text>"
        )

    def group_start(
        self, *, opacity: float = 1.0, transform: str | None = None
    ) -> None:
        """Open an SVG group element."""
        self._elements.append(
            f"<g {_attrs(**_maybe(opacity=opacity, transform=transform))}>"
        )

    def group_end(self) -> None:
        """Close the most recent SVG group element."""
        self._elements.append("</g>")

    def to_document(self) -> SvgDocument:
        """Return the current canvas as an SVG document."""
        content = [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{self.width}" height="{self.height}" '
                f'viewBox="0 0 {self.width} {self.height}">'
            ),
            (
                f'<rect class="svg-document__background" x="0" y="0" '
                f'width="{self.width}" height="{self.height}" '
                f'fill="{self.background}"/>'
            ),
            *self._elements,
            "</svg>",
        ]
        return SvgDocument(
            width=self.width,
            height=self.height,
            svg="\n".join(content),
        )


def _maybe(**values: object) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            if not value:
                continue
            attributes[key] = "true"
        elif isinstance(value, float):
            if value == 0.0 and key != "opacity":
                continue
            attributes[key] = _fmt(value)
        else:
            attributes[key] = str(value)
    return attributes


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _attrs(**attributes: object) -> str:
    parts: list[str] = []
    for key, value in attributes.items():
        if value is None:
            continue
        key_name = key.replace("_", "-")
        parts.append(f'{key_name}="{escape(str(value))}"')
    return " ".join(parts)


def _tag(name: str, **attributes: object) -> str:
    return f"<{name} {_attrs(**attributes)}/>"


def _dashboard_section_markup(section: SvgDashboardSection) -> str:
    description_markup = ""
    if section.description is not None:
        description_markup = f"<p>{escape(section.description)}</p>"
    featured_panel = section.panels[0] if section.panels else None
    secondary_panels = section.panels[1:] if len(section.panels) > 1 else []
    featured_markup = ""
    if featured_panel is not None:
        featured_markup = (
            '<div class="dashboard__featured">'
            f"{_dashboard_panel_markup(featured_panel, featured=True)}"
            "</div>"
        )
    grid_markup = ""
    if secondary_panels:
        grid_markup = (
            '<div class="dashboard__grid">'
            + "\n".join(
                _dashboard_panel_markup(panel) for panel in secondary_panels
            )
            + "</div>"
        )
    return f"""<section class="dashboard__section" id="{_slugify(section.title)}">
  <header class="dashboard__section-header">
    <h2>{escape(section.title)}</h2>
    {description_markup}
  </header>
  {featured_markup}
  {grid_markup}
</section>"""


def _dashboard_panel_markup(
    panel: SvgDashboardPanel, *, featured: bool = False
) -> str:
    description_markup = ""
    if panel.description is not None:
        description_markup = f"<p>{escape(panel.description)}</p>"
    hint_markup = '<p class="dashboard-card__hint">Click to expand.</p>'
    svg_markup = panel.document.svg.replace(
        "<svg ",
        '<svg class="dashboard-card__svg" ',
        1,
    )
    card_class = "dashboard-card dashboard-card--featured"
    if not featured:
        card_class = "dashboard-card"
    return f"""<article class="{card_class}">
  <header class="dashboard-card__header">
    <h3>{escape(panel.title)}</h3>
    {description_markup}
    {hint_markup}
  </header>
  <button
    class="dashboard-card__viewport"
    type="button"
    data-panel-title="{escape(panel.title)}"
    data-panel-description="{escape(panel.description or "")}"
    aria-label="Expand {escape(panel.title)}"
  >
    {svg_markup}
  </button>
</article>"""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "section"
