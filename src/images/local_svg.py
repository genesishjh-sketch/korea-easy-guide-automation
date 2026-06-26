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
    scene = _windows_scene(f"{keyword} {title}")
    (assets_dir / "ai-hero.svg").write_text(_hero_svg(title, keyword, scene), encoding="utf-8")
    (assets_dir / "ai-inline-1.svg").write_text(_inline_svg(keyword, scene), encoding="utf-8")


def _hero_svg(title: str, keyword: str, scene: str) -> str:
    safe_title = escape(title)
    config = _windows_scene_config(scene)
    prop = _hero_prop(scene)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 788" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="{config['bg1']}"/>
      <stop offset="0.58" stop-color="{config['bg2']}"/>
      <stop offset="1" stop-color="{config['bg3']}"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="24" stdDeviation="28" flood-color="#172033" flood-opacity="0.13"/>
    </filter>
    <linearGradient id="screen" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#eff6ff"/>
      <stop offset="1" stop-color="{config['screen']}"/>
    </linearGradient>
  </defs>
  <rect width="1400" height="788" fill="url(#bg)"/>
  <path d="M0 646c180-80 330-48 506-116 190-72 356-44 520-108 132-52 246-66 374-42v408H0z" fill="{config['desk']}" opacity=".92"/>
  <g transform="translate(104 110)" filter="url(#shadow)">
    <rect x="0" y="0" width="1192" height="560" rx="42" fill="#ffffff" stroke="#dde7ee"/>
    <rect x="64" y="84" width="642" height="372" rx="30" fill="#172033"/>
    <rect x="100" y="120" width="570" height="296" rx="18" fill="url(#screen)"/>
    <path d="{config['screen_path']}" fill="none" stroke="{config['accent']}" stroke-width="22" stroke-linecap="round" opacity=".9"/>
    <path d="{config['screen_path_2']}" fill="none" stroke="{config['accent2']}" stroke-width="14" stroke-linecap="round" opacity=".78"/>
    <rect x="286" y="456" width="142" height="28" rx="14" fill="#172033"/>
    <rect x="12" y="492" width="760" height="34" rx="17" fill="#d5dee7"/>
    <g transform="translate(780 88)">
      <rect x="0" y="0" width="310" height="160" rx="28" fill="{config['card']}" stroke="#d8e4ec" stroke-width="4"/>
      <circle cx="74" cy="80" r="34" fill="{config['accent']}" opacity=".18"/>
      <path d="{config['icon']}" fill="none" stroke="{config['accent']}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M150 58h104M150 86h78M150 114h126" stroke="#9aa8b5" stroke-width="12" stroke-linecap="round"/>
    </g>
    {prop}
  </g>
</svg>"""


def _inline_svg(keyword: str, scene: str) -> str:
    safe_keyword = escape(keyword.title())
    config = _windows_scene_config(scene)
    steps = _inline_steps(scene)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 788" role="img" aria-label="Step-by-step troubleshooting illustration for {safe_keyword}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="{config['bg1']}"/>
      <stop offset="1" stop-color="{config['bg3']}"/>
    </linearGradient>
    <filter id="shadow" x="-18%" y="-18%" width="136%" height="136%">
      <feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#172033" flood-opacity=".11"/>
    </filter>
  </defs>
  <rect width="1400" height="788" fill="url(#bg)"/>
  <g transform="translate(94 92)">
    <rect x="0" y="0" width="1212" height="604" rx="42" fill="#ffffff" stroke="#dfe8ef"/>
    <g transform="translate(82 78)" filter="url(#shadow)">
      {_step_card(0, steps[0], config, "#eaf3ff")}
      {_step_card(366, steps[1], config, "#ecfdf5")}
      {_step_card(732, steps[2], config, "#fff7ed")}
    </g>
    <path d="M382 238h98M748 238h98" stroke="#9aa8b5" stroke-width="12" stroke-linecap="round"/>
    <g transform="translate(82 438)">
      <rect width="1048" height="94" rx="26" fill="{config['note']}" stroke="#d8e4ec"/>
      <path d="M48 47l28 28 58-64" fill="none" stroke="{config['accent']}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M176 34h750M176 62h560" stroke="#718093" stroke-width="13" stroke-linecap="round" opacity=".62"/>
    </g>
  </g>
</svg>"""


def _step_card(x: int, icon: str, config: dict[str, str], fill: str) -> str:
    return f"""<g transform="translate({x} 0)">
        <rect width="316" height="258" rx="30" fill="{fill}" stroke="#d8e4ec"/>
        <circle cx="158" cy="102" r="58" fill="#ffffff" opacity=".85"/>
        <path d="{icon}" fill="none" stroke="{config['accent']}" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M76 192h164M104 222h108" stroke="#718093" stroke-width="12" stroke-linecap="round" opacity=".58"/>
      </g>"""


def _windows_scene(text: str) -> str:
    value = text.lower()
    if any(token in value for token in ["wi-fi", "wifi", "internet", "network"]):
        return "network"
    if "bluetooth" in value or "device" in value:
        return "device"
    if any(token in value for token in ["sound", "audio", "microphone", "mic"]):
        return "audio"
    if any(token in value for token in ["printer", "scanner"]):
        return "printer"
    if any(token in value for token in ["onedrive", "account", "sign in", "sync"]):
        return "account"
    if any(token in value for token in ["search", "file explorer", "folder", "explorer"]):
        return "files"
    if any(token in value for token in ["boot", "startup", "recovery", "repair"]):
        return "recovery"
    if any(token in value for token in ["version", "edition", "build", "about windows"]):
        return "version"
    if any(token in value for token in ["update", "restart", "0x", "error code"]):
        return "update"
    return "general"


def _windows_scene_config(scene: str) -> dict[str, str]:
    configs = {
        "network": {
            "bg1": "#f7fcfb", "bg2": "#eefaf7", "bg3": "#f5fbff", "desk": "#d7eee9",
            "screen": "#dff7f0", "accent": "#0f766e", "accent2": "#2563eb", "card": "#f0fdfa", "note": "#ecfdf5",
            "screen_path": "M170 276c72-72 188-72 260 0", "screen_path_2": "M216 320c42-34 96-34 138 0",
            "icon": "M54 92c42-42 110-42 152 0M82 122c26-22 70-22 96 0M130 146h1",
        },
        "device": {
            "bg1": "#f8fbff", "bg2": "#f1f5ff", "bg3": "#f8fafc", "desk": "#dce6f3",
            "screen": "#e9efff", "accent": "#4f46e5", "accent2": "#0891b2", "card": "#eef2ff", "note": "#eef2ff",
            "screen_path": "M206 198h154a48 48 0 010 96H206a48 48 0 010-96", "screen_path_2": "M228 324h112",
            "icon": "M70 60h74a42 42 0 010 84H70a42 42 0 010-84M196 102h38",
        },
        "audio": {
            "bg1": "#fbfdf8", "bg2": "#f2fbef", "bg3": "#fffaf2", "desk": "#e8eed7",
            "screen": "#eef9e8", "accent": "#16a34a", "accent2": "#f59e0b", "card": "#f0fdf4", "note": "#f7fee7",
            "screen_path": "M180 304c36-70 118-70 154 0M142 260c76-118 230-118 306 0", "screen_path_2": "M226 338h176",
            "icon": "M72 120V82a62 62 0 01124 0v38M72 120h28v56H72zM168 120h28v56h-28z",
        },
        "printer": {
            "bg1": "#f8fcff", "bg2": "#eef9fc", "bg3": "#f8fafc", "desk": "#d8edf3",
            "screen": "#e4f5fb", "accent": "#0891b2", "accent2": "#64748b", "card": "#ecfeff", "note": "#ecfeff",
            "screen_path": "M176 208h258v168H176z", "screen_path_2": "M214 258h182M214 306h124",
            "icon": "M82 78h132v58H82zM58 136h180v84H58zM96 220h104",
        },
        "files": {
            "bg1": "#fffdf7", "bg2": "#fff7e6", "bg3": "#f8fafc", "desk": "#eee2c7",
            "screen": "#fff2cf", "accent": "#d97706", "accent2": "#2563eb", "card": "#fffbeb", "note": "#fffbeb",
            "screen_path": "M166 214h126l30 34h134v118H166z", "screen_path_2": "M248 318l70 70M318 318l-70 70",
            "icon": "M58 96h92l24 28h96v104H58zM178 188l58 58M236 188l-58 58",
        },
        "recovery": {
            "bg1": "#fff8f8", "bg2": "#fef2f2", "bg3": "#f8fafc", "desk": "#efdada",
            "screen": "#fee2e2", "accent": "#dc2626", "accent2": "#0f766e", "card": "#fff1f2", "note": "#fff1f2",
            "screen_path": "M292 176l118 62v86c0 74-48 122-118 150-70-28-118-76-118-150v-86z", "screen_path_2": "M244 314l36 36 78-90",
            "icon": "M148 52l92 48v68c0 58-36 94-92 116-56-22-92-58-92-116v-68zM106 162l30 30 62-76",
        },
        "version": {
            "bg1": "#f8fbff", "bg2": "#eef4ff", "bg3": "#f5f7fb", "desk": "#dce5f1",
            "screen": "#e5edff", "accent": "#2563eb", "accent2": "#7c3aed", "card": "#eff6ff", "note": "#eff6ff",
            "screen_path": "M178 190h258v82H178zM178 314h258v82H178z", "screen_path_2": "M216 232h154M216 356h94",
            "icon": "M70 70h154v154H70zM108 108h44M108 148h80M108 188h60",
        },
        "update": {
            "bg1": "#f8fbff", "bg2": "#eef4ff", "bg3": "#f8fafc", "desk": "#dbe8f7",
            "screen": "#dbeafe", "accent": "#2563eb", "accent2": "#0f766e", "card": "#eff6ff", "note": "#eff6ff",
            "screen_path": "M182 280a110 110 0 01188-78M386 204v72h-72", "screen_path_2": "M430 284a110 110 0 01-188 78M226 360v-72h72",
            "icon": "M88 146a70 70 0 01120-50M220 98v48h-48M208 162a70 70 0 01-120 50M76 210v-48h48",
        },
        "general": {
            "bg1": "#f8fbff", "bg2": "#f2f7fb", "bg3": "#eefaf7", "desk": "#dbeadf",
            "screen": "#dbeafe", "accent": "#2563eb", "accent2": "#0f766e", "card": "#f8fbfd", "note": "#f8fbfd",
            "screen_path": "M190 292l54 54 136-150", "screen_path_2": "M176 394h260",
            "icon": "M82 96l38 38 84-90M78 190h150",
        },
    }
    return configs.get(scene, configs["general"])


def _hero_prop(scene: str) -> str:
    props = {
        "network": """<g transform="translate(850 328)"><rect width="180" height="86" rx="24" fill="#172033"/><path d="M42 44h96" stroke="#f8fafc" stroke-width="10" stroke-linecap="round"/><circle cx="48" cy="64" r="7" fill="#34d399"/><circle cx="76" cy="64" r="7" fill="#93c5fd"/><path d="M116 18v-52" stroke="#172033" stroke-width="12" stroke-linecap="round"/></g>""",
        "device": """<g transform="translate(852 328)"><rect width="190" height="108" rx="54" fill="#f8fafc" stroke="#cfd9e5" stroke-width="6"/><circle cx="62" cy="54" r="18" fill="#4f46e5"/><circle cx="128" cy="54" r="18" fill="#0891b2"/></g>""",
        "audio": """<g transform="translate(840 310)"><path d="M40 92V62a74 74 0 01148 0v30" fill="none" stroke="#172033" stroke-width="18" stroke-linecap="round"/><rect x="16" y="88" width="42" height="88" rx="18" fill="#16a34a"/><rect x="170" y="88" width="42" height="88" rx="18" fill="#16a34a"/></g>""",
        "printer": """<g transform="translate(826 304)"><rect x="42" y="0" width="210" height="110" rx="14" fill="#f8fafc" stroke="#cfd9e5" stroke-width="6"/><rect x="0" y="88" width="294" height="142" rx="26" fill="#172033"/><rect x="58" y="160" width="178" height="74" rx="12" fill="#ecfeff"/></g>""",
        "files": """<g transform="translate(826 318)"><path d="M0 44h118l28 36h184v158H0z" fill="#fffbeb" stroke="#d6a03b" stroke-width="6"/><circle cx="238" cy="86" r="44" fill="none" stroke="#d97706" stroke-width="14"/><path d="M270 118l54 54" stroke="#d97706" stroke-width="14" stroke-linecap="round"/></g>""",
        "recovery": """<g transform="translate(850 296)"><rect width="170" height="230" rx="24" fill="#172033"/><circle cx="85" cy="58" r="18" fill="#dc2626"/><path d="M86 92l70 38v54c0 45-28 74-70 92-42-18-70-47-70-92v-54z" fill="#fff1f2" stroke="#dc2626" stroke-width="8"/></g>""",
        "version": """<g transform="translate(828 310)"><rect width="300" height="210" rx="28" fill="#eff6ff" stroke="#cbd5e1" stroke-width="6"/><path d="M56 62h188M56 106h142M56 150h176" stroke="#2563eb" stroke-width="14" stroke-linecap="round"/></g>""",
        "update": """<g transform="translate(850 310)"><circle cx="116" cy="112" r="96" fill="#eff6ff" stroke="#bfdbfe" stroke-width="6"/><path d="M70 112a54 54 0 0192-38M168 74v42h-42M162 126a54 54 0 01-92 38M64 164v-42h42" fill="none" stroke="#2563eb" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></g>""",
        "general": """<g transform="translate(840 318)"><rect width="296" height="194" rx="30" fill="#f8fbfd" stroke="#d8e4ec" stroke-width="6"/><path d="M62 102l48 48 118-126" fill="none" stroke="#0f766e" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/></g>""",
    }
    return props.get(scene, props["general"])


def _inline_steps(scene: str) -> tuple[str, str, str]:
    steps = {
        "network": ("M90 116c40-40 104-40 144 0M116 146c24-20 64-20 88 0M160 176h1", "M86 90h148v108H86zM116 122h88M116 156h58", "M92 164a68 68 0 01116-48M218 116v48h-48"),
        "device": ("M78 116h90a42 42 0 010 84H78a42 42 0 010-84", "M100 90h120M100 132h82M100 174h106", "M86 154c42-42 110-42 152 0M120 188c22-20 62-20 84 0"),
        "audio": ("M82 156V116a76 76 0 01152 0v40M82 156h32v58H82zM202 156h32v58h-32z", "M96 92v122M154 122v68M212 78v150", "M82 160l42 42 96-112"),
        "printer": ("M84 92h150v60H84zM58 152h202v88H58z", "M94 96h128M94 136h92M94 176h116", "M82 164a68 68 0 01116-48M208 116v48h-48"),
        "files": ("M58 116h96l24 28h112v112H58z", "M96 102h132M96 144h86M96 186h110", "M118 156l44 44 88-104"),
        "recovery": ("M158 62l102 54v80c0 62-42 102-102 126-60-24-102-64-102-126v-80z", "M82 168l42 42 96-112", "M90 108h148M90 154h96M90 200h126"),
        "version": ("M76 84h168v168H76zM112 124h54M112 166h102M112 208h72", "M96 100h128M96 146h96M96 192h116", "M82 164a68 68 0 01116-48M208 116v48h-48"),
        "update": ("M92 164a68 68 0 01116-48M218 116v48h-48", "M92 112h132M92 154h86M92 196h112", "M82 168l42 42 96-112"),
        "general": ("M82 168l42 42 96-112", "M92 112h132M92 154h86M92 196h112", "M92 164a68 68 0 01116-48M218 116v48h-48"),
    }
    return steps.get(scene, steps["general"])


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
