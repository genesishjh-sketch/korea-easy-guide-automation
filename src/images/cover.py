from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from slugify import slugify

from src.models import ImageAsset


def create_local_svg_cover(title: str, output_dir: Path) -> ImageAsset:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify(title)[:70]}-cover.svg"
    path = output_dir / filename
    safe_title = escape(title)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="sky" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#e8f6ff"/>
      <stop offset="0.52" stop-color="#fff7e8"/>
      <stop offset="1" stop-color="#dff5ef"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#sky)"/>
  <rect x="0" y="460" width="1200" height="215" fill="#eef4f7"/>
  <path d="M610 310h42v150h-42zM674 260h54v200h-54zM748 292h40v168h-40zM812 228h68v232h-68zM902 280h46v180h-46zM974 168h64v292h-64zM1060 292h54v168h-54z" fill="#60758a"/>
  <path d="M1004 70l34 98h-64z" fill="#51677c"/>
  <path d="M585 468h575" stroke="#64798a" stroke-width="14"/>
  <path d="M90 500h360" stroke="#cbd5df" stroke-width="12" stroke-linecap="round"/>
  <circle cx="200" cy="300" r="42" fill="#263243"/>
  <path d="M150 378c16-54 84-54 100 0l26 156H124z" fill="#0f766e"/>
  <rect x="296" y="420" width="92" height="128" rx="12" fill="#64748b"/>
  <rect x="316" y="392" width="52" height="38" rx="12" fill="none" stroke="#475569" stroke-width="9"/>
  <path d="M0 95h505M0 202h505M0 309h505" stroke="#d7e5eb" stroke-width="9"/>
  <path d="M108 0v454M250 0v454M392 0v454" stroke="#d7e5eb" stroke-width="9"/>
  <text x="70" y="620" fill="#1f2937" font-family="Arial, sans-serif" font-size="34" font-weight="700">Korea Easy Guide</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    return ImageAsset(
        path=str(path),
        url=f"assets/{path.name}",
        alt=title,
        source="local_svg",
        credit="Generated local SVG cover",
    )
