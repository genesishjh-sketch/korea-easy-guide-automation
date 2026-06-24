from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from src.images.cover import detect_scene
from src.images.cover import render_cover


def create_korea_svg_assets(article_dir: Path, title: str, keyword: str) -> None:
    assets_dir = article_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    scene = detect_scene(f"{keyword} {title}")
    (assets_dir / "ai-hero.svg").write_text(render_cover(title, scene), encoding="utf-8")
    (assets_dir / "ai-inline-1.svg").write_text(_korea_inline_svg(keyword, scene), encoding="utf-8")


def create_windows_svg_assets(article_dir: Path, title: str, keyword: str) -> None:
    assets_dir = article_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "ai-hero.svg").write_text(_hero_svg(title, keyword), encoding="utf-8")
    (assets_dir / "ai-inline-1.svg").write_text(_inline_svg(keyword), encoding="utf-8")


def _hero_svg(title: str, keyword: str) -> str:
    safe_title = escape(title)
    safe_keyword = escape(keyword.title())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 788" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#f8fbff"/>
      <stop offset="0.58" stop-color="#f2f7fb"/>
      <stop offset="1" stop-color="#eefaf7"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="24" stdDeviation="28" flood-color="#172033" flood-opacity="0.13"/>
    </filter>
  </defs>
  <rect width="1400" height="788" fill="url(#bg)"/>
  <path d="M0 612C196 512 322 602 514 512c202-95 342-30 516-120 128-66 238-68 370-36" fill="none" stroke="#bfdbfe" stroke-width="34" stroke-linecap="round" opacity=".72"/>
  <g filter="url(#shadow)">
    <rect x="94" y="88" width="1212" height="612" rx="38" fill="#ffffff" stroke="#d8e4ec"/>
  </g>
  <g transform="translate(150 150)">
    <rect width="360" height="58" rx="29" fill="#eaf3ff"/>
    <circle cx="34" cy="29" r="10" fill="#2563eb"/>
    <text x="58" y="37" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="700" fill="#17335f">Beginner Windows Help</text>
    <text x="0" y="150" font-family="Arial, Helvetica, sans-serif" font-size="52" font-weight="800" fill="#172033">Safe PC Fix Guide</text>
    <text x="0" y="206" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" fill="#526173">{safe_keyword}</text>
    <text x="0" y="482" font-family="Arial, Helvetica, sans-serif" font-size="36" font-weight="800" fill="#172033">Easy PC Fix Guide</text>
  </g>
  <g transform="translate(700 168)">
    <rect x="0" y="80" width="470" height="300" rx="24" fill="#172033"/>
    <rect x="28" y="108" width="414" height="236" rx="14" fill="#dbeafe"/>
    <path d="M84 250c72-72 188-72 260 0" fill="none" stroke="#2563eb" stroke-width="22" stroke-linecap="round"/>
    <path d="M130 296c46-42 122-42 168 0" fill="none" stroke="#0f766e" stroke-width="18" stroke-linecap="round"/>
    <circle cx="214" cy="330" r="16" fill="#0f766e"/>
    <rect x="170" y="382" width="130" height="22" rx="11" fill="#172033"/>
    <rect x="-36" y="430" width="542" height="38" rx="19" fill="#d8e4ec"/>
    <g transform="translate(348 0)">
      <rect width="210" height="126" rx="22" fill="#f8fbfd" stroke="#d8e4ec" stroke-width="4"/>
      <circle cx="56" cy="64" r="16" fill="#0f766e"/>
      <circle cx="104" cy="64" r="16" fill="#2563eb"/>
      <circle cx="152" cy="64" r="16" fill="#f59e0b"/>
      <path d="M40 98h130" stroke="#d8e4ec" stroke-width="10" stroke-linecap="round"/>
    </g>
  </g>
</svg>"""


def _inline_svg(keyword: str) -> str:
    safe_keyword = escape(keyword.title())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 788" role="img" aria-label="Step-by-step troubleshooting diagram for {safe_keyword}">
  <rect width="1400" height="788" fill="#f8fbfd"/>
  <g transform="translate(100 100)">
    <text x="0" y="46" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="800" fill="#172033">Safe Troubleshooting Order</text>
    <text x="0" y="92" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="700" fill="#526173">{safe_keyword}</text>
    <g font-family="Arial, Helvetica, sans-serif" font-size="25" font-weight="700">
      <rect x="0" y="150" width="250" height="150" rx="24" fill="#eaf3ff" stroke="#bfdbfe"/>
      <text x="42" y="236" fill="#17335f">Restart</text>
      <path d="M274 225h110" stroke="#9ca3af" stroke-width="10" stroke-linecap="round"/>
      <rect x="410" y="150" width="250" height="150" rx="24" fill="#ecfdf5" stroke="#bbf7d0"/>
      <text x="456" y="236" fill="#14532d">Check Wi-Fi</text>
      <path d="M684 225h110" stroke="#9ca3af" stroke-width="10" stroke-linecap="round"/>
      <rect x="820" y="150" width="250" height="150" rx="24" fill="#fff7ed" stroke="#fed7aa"/>
      <text x="865" y="236" fill="#7c2d12">Troubleshooter</text>
      <path d="M500 326v110" stroke="#9ca3af" stroke-width="10" stroke-linecap="round"/>
      <rect x="310" y="470" width="380" height="150" rx="24" fill="#fef2f2" stroke="#fecaca"/>
      <text x="356" y="556" fill="#7f1d1d">Advanced only if needed</text>
    </g>
    <text x="0" y="690" font-family="Arial, Helvetica, sans-serif" font-size="23" font-weight="700" fill="#526173">Start with reversible steps. Stop if files, drives, BitLocker, or repeated blue screens are involved.</text>
  </g>
</svg>"""


def _korea_inline_svg(keyword: str, scene: str) -> str:
    safe_keyword = escape(keyword.title())
    title = {
        "airport": "Compare Your Transfer Options",
        "ktx": "Check the Train Details First",
        "esim": "Set Up Mobile Data Before Moving",
        "taxi": "Confirm Pickup and Destination",
        "map": "Check Route Details Before Walking",
        "transport_card": "Buy, Recharge, Tap",
        "shopping": "Check Payment and App Requirements",
    }.get(scene, "Follow the Practical Steps")
    steps = {
        "airport": ("Airport", "Train / Bus / Taxi", "Hotel Area"),
        "ktx": ("Station", "Ticket Details", "Platform"),
        "esim": ("QR / App", "Mobile Data", "Maps Ready"),
        "taxi": ("Pickup Point", "Car Info", "Destination"),
        "map": ("Search", "Compare Routes", "Move Safely"),
        "transport_card": ("Buy Card", "Recharge", "Tap Gate"),
        "shopping": ("Open App", "Check Payment", "Confirm Address"),
    }.get(scene, ("Start", "Check", "Go"))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 788" role="img" aria-label="{escape(title)} for {safe_keyword}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#f8fbff"/>
      <stop offset="0.55" stop-color="#fffaf2"/>
      <stop offset="1" stop-color="#eef9f5"/>
    </linearGradient>
    <filter id="shadow" x="-18%" y="-18%" width="136%" height="136%">
      <feDropShadow dx="0" dy="20" stdDeviation="24" flood-color="#172033" flood-opacity="0.12"/>
    </filter>
  </defs>
  <rect width="1400" height="788" fill="url(#bg)"/>
  <g transform="translate(96 88)">
    <text x="0" y="54" font-family="Arial, Helvetica, sans-serif" font-size="44" font-weight="800" fill="#172033">{escape(title)}</text>
    <text x="0" y="98" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="700" fill="#526173">{safe_keyword}</text>
    <g filter="url(#shadow)" font-family="Arial, Helvetica, sans-serif" font-weight="800">
      <rect x="0" y="170" width="330" height="210" rx="28" fill="#ffffff" stroke="#d8e4ec"/>
      <circle cx="68" cy="245" r="30" fill="#dbeafe"/>
      <text x="58" y="256" font-size="31" fill="#2563eb">1</text>
      <text x="42" y="326" font-size="30" fill="#172033">{escape(steps[0])}</text>
      <path d="M354 275h120" stroke="#9ca3af" stroke-width="12" stroke-linecap="round"/>
      <rect x="500" y="170" width="330" height="210" rx="28" fill="#ffffff" stroke="#d8e4ec"/>
      <circle cx="568" cy="245" r="30" fill="#dcfce7"/>
      <text x="558" y="256" font-size="31" fill="#0f766e">2</text>
      <text x="542" y="326" font-size="30" fill="#172033">{escape(steps[1])}</text>
      <path d="M854 275h120" stroke="#9ca3af" stroke-width="12" stroke-linecap="round"/>
      <rect x="1000" y="170" width="330" height="210" rx="28" fill="#ffffff" stroke="#d8e4ec"/>
      <circle cx="1068" cy="245" r="30" fill="#fef3c7"/>
      <text x="1058" y="256" font-size="31" fill="#ca8a04">3</text>
      <text x="1042" y="326" font-size="30" fill="#172033">{escape(steps[2])}</text>
    </g>
    <rect x="0" y="480" width="1228" height="104" rx="28" fill="#ffffff" stroke="#d8e4ec"/>
    <text x="42" y="544" font-family="Arial, Helvetica, sans-serif" font-size="26" font-weight="700" fill="#526173">Use this as a quick visual checklist before relying on apps, transport, tickets, or local services in Korea.</text>
  </g>
</svg>"""
