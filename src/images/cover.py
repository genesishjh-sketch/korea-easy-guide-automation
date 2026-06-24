from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from slugify import slugify

from src.models import ImageAsset


BRAND_TEXT = "Korea Easy Guide"

SCENE_META = {
    "airport": {
        "label": "Airport Transfer",
        "headline": "Airport to Seoul",
        "accent": "#2563eb",
        "soft": "#dbeafe",
    },
    "ktx": {
        "label": "KTX Train Guide",
        "headline": "KTX Tickets in Korea",
        "accent": "#0f766e",
        "soft": "#ccfbf1",
    },
    "esim": {
        "label": "Mobile Internet",
        "headline": "Korea eSIM Guide",
        "accent": "#7c3aed",
        "soft": "#ede9fe",
    },
    "taxi": {
        "label": "Taxi App Guide",
        "headline": "Kakao T Taxi",
        "accent": "#ca8a04",
        "soft": "#fef3c7",
    },
    "map": {
        "label": "Navigation Guide",
        "headline": "Naver Map in Korea",
        "accent": "#dc2626",
        "soft": "#fee2e2",
    },
    "shopping": {
        "label": "Daily Life Guide",
        "headline": "Shopping and Daily Life",
        "accent": "#0f766e",
        "soft": "#dcfce7",
    },
    "city": {
        "label": "Korea Travel Guide",
        "headline": "Korea Travel Made Easier",
        "accent": "#2563eb",
        "soft": "#dbeafe",
    },
}


def create_local_svg_cover(title: str, output_dir: Path) -> ImageAsset:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify(title)[:70]}-cover.svg"
    path = output_dir / filename
    scene = detect_scene(title)
    svg = render_cover(title, scene)
    path.write_text(svg, encoding="utf-8")
    return ImageAsset(
        path=str(path),
        url=f"assets/{path.name}",
        alt=title,
        source=f"local_svg_{scene}",
        credit="Generated local SVG cover",
    )


def detect_scene(title: str) -> str:
    text = title.lower()
    if any(word in text for word in ("ktx", "train", "rail")):
        return "ktx"
    if any(word in text for word in ("esim", "sim", "mobile", "internet", "wifi")):
        return "esim"
    if any(word in text for word in ("taxi", "kakao t", "kakao taxi")):
        return "taxi"
    if any(word in text for word in ("naver map", "kakaomap", "map", "navigation")):
        return "map"
    if any(word in text for word in ("t money", "t-money", "tmoney", "transportation card", "transit card")):
        return "transport_card"
    if any(word in text for word in ("airport", "incheon", "seoul station", "bus", "transport")):
        return "airport"
    if any(word in text for word in ("coupang", "delivery", "shopping", "store", "convenience")):
        return "shopping"
    return "city"


def render_cover(title: str, scene: str) -> str:
    meta = SCENE_META.get(scene, SCENE_META["city"])
    accent = meta["accent"]
    soft = meta["soft"]
    safe_title = escape(title)
    drawing = {
        "airport": airport_scene,
        "ktx": ktx_scene,
        "esim": esim_scene,
        "taxi": taxi_scene,
        "map": map_scene,
        "shopping": shopping_scene,
        "city": city_scene,
    }.get(scene, city_scene)(accent, soft)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#f6fbff"/>
      <stop offset="0.52" stop-color="#fffaf2"/>
      <stop offset="1" stop-color="#eef9f5"/>
    </linearGradient>
    <linearGradient id="panel" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#f7fbfd"/>
    </linearGradient>
    <filter id="shadow" x="-18%" y="-18%" width="136%" height="136%">
      <feDropShadow dx="0" dy="22" stdDeviation="24" flood-color="#172033" flood-opacity="0.12"/>
    </filter>
  </defs>
  <rect width="1200" height="675" fill="url(#bg)"/>
  <g opacity="0.45">
    <path d="M0 170h1200M0 300h1200M0 430h1200M190 0v675M390 0v675M590 0v675M790 0v675M990 0v675" stroke="#dce8ef" stroke-width="2"/>
    <path d="M96 520C264 446 346 494 520 438c190-61 313-19 514-84" fill="none" stroke="{soft}" stroke-width="26" stroke-linecap="round"/>
    <path d="M96 520C264 446 346 494 520 438c190-61 313-19 514-84" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" opacity="0.72"/>
  </g>
  <g filter="url(#shadow)">
    <rect x="72" y="58" width="1056" height="548" rx="34" fill="url(#panel)" stroke="#d9e6ed"/>
  </g>
  <g>
    <rect x="112" y="98" width="220" height="42" rx="21" fill="{soft}"/>
    <circle cx="137" cy="119" r="7" fill="{accent}"/>
    <text x="154" y="126" fill="#233044" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700">{escape(meta["label"])}</text>
    <text x="112" y="206" fill="#172033" font-family="Arial, Helvetica, sans-serif" font-size="39" font-weight="800">{escape(meta["headline"])}</text>
    <text x="112" y="250" fill="#526173" font-family="Arial, Helvetica, sans-serif" font-size="22" font-weight="700">Practical guide for foreign visitors</text>
    <text x="112" y="532" fill="#172033" font-family="Arial, Helvetica, sans-serif" font-size="32" font-weight="800">{BRAND_TEXT}</text>
  </g>
  {drawing}
</svg>
"""


def airport_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(530 116)">
    <rect x="0" y="0" width="486" height="332" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="3"/>
    <path d="M48 246h388" stroke="#e1ebf2" stroke-width="10" stroke-linecap="round"/>
    <path d="M72 219h78M214 219h78M356 219h58" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>
    <path d="M84 126l124-38 148 56c23 9 42 25 54 46l17 30-213-44-88 43c-24 12-52-6-52-33v-36c0-11 3-20 10-24z" fill="{soft}" stroke="#526173" stroke-width="5" stroke-linejoin="round"/>
    <path d="M204 92l40-54h50l-23 72" fill="#ffffff" stroke="#526173" stroke-width="5" stroke-linejoin="round"/>
    <path d="M346 143l67-38h48l-47 61" fill="#ffffff" stroke="#526173" stroke-width="5" stroke-linejoin="round"/>
    <circle cx="160" cy="238" r="18" fill="#172033"/>
    <circle cx="344" cy="238" r="18" fill="#172033"/>
    <rect x="50" y="34" width="150" height="52" rx="16" fill="#f7fbfd" stroke="#d9e6ed" stroke-width="3"/>
    <text x="70" y="67" fill="{accent}" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="800">ICN to Seoul</text>
  </g>"""


def ktx_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(498 118)">
    <rect x="0" y="0" width="528" height="330" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="3"/>
    <path d="M50 200c30-72 91-114 186-126l174-22c37-5 74 12 94 45l34 56c19 31-3 71-39 71H70c-18 0-28-14-20-24z" fill="#f9fcfe" stroke="#526173" stroke-width="6" stroke-linejoin="round"/>
    <path d="M205 87l202-24c31-4 62 7 81 30H148c14-3 32-5 57-6z" fill="{soft}"/>
    <path d="M72 194h433" stroke="{accent}" stroke-width="12" stroke-linecap="round"/>
    <circle cx="146" cy="242" r="24" fill="#172033"/>
    <circle cx="420" cy="242" r="24" fill="#172033"/>
    <path d="M70 284h404" stroke="#d8e4ec" stroke-width="10" stroke-linecap="round"/>
    <path d="M100 304h330" stroke="#e7eef3" stroke-width="6" stroke-linecap="round"/>
    <text x="52" y="62" fill="{accent}" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="800">KTX</text>
  </g>"""


def esim_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(548 102)">
    <rect x="0" y="0" width="214" height="382" rx="32" fill="#172033"/>
    <rect x="18" y="48" width="178" height="278" rx="18" fill="#f8fbfd"/>
    <circle cx="107" cy="350" r="10" fill="#dbe5ee"/>
    <path d="M62 160c31-29 59-29 90 0M82 190c18-17 32-17 50 0M103 221c4-4 7-4 11 0" fill="none" stroke="{accent}" stroke-width="12" stroke-linecap="round"/>
    <rect x="262" y="54" width="214" height="246" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="4"/>
    <path d="M409 54v64h67" fill="none" stroke="#d9e6ed" stroke-width="4"/>
    <rect x="300" y="136" width="138" height="46" rx="14" fill="{soft}"/>
    <text x="321" y="168" fill="{accent}" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="800">eSIM</text>
    <path d="M244 185h48" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>
    <path d="M278 162l28 27-28 27" fill="none" stroke="{accent}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
  </g>"""


def taxi_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(520 120)">
    <rect x="0" y="0" width="506" height="328" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="3"/>
    <path d="M64 232h380" stroke="#e5edf3" stroke-width="10" stroke-linecap="round"/>
    <path d="M104 176l48-76h190l62 76h32c24 0 44 20 44 44v30H62v-30c0-24 20-44 44-44z" fill="{soft}" stroke="#233044" stroke-width="5" stroke-linejoin="round"/>
    <path d="M169 111h148l38 65H128z" fill="#f8fbfd" stroke="#233044" stroke-width="4"/>
    <circle cx="152" cy="252" r="27" fill="#172033"/>
    <circle cx="388" cy="252" r="27" fill="#172033"/>
    <circle cx="152" cy="252" r="10" fill="#dbe5ee"/>
    <circle cx="388" cy="252" r="10" fill="#dbe5ee"/>
    <rect x="222" y="66" width="86" height="38" rx="13" fill="#172033"/>
    <text x="240" y="92" fill="#ffffff" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="800">TAXI</text>
    <rect x="42" y="36" width="126" height="52" rx="18" fill="#f8fbfd" stroke="#d9e6ed" stroke-width="3"/>
    <circle cx="74" cy="62" r="12" fill="{accent}"/>
    <text x="95" y="69" fill="#233044" font-family="Arial, Helvetica, sans-serif" font-size="19" font-weight="800">App call</text>
  </g>"""


def map_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(514 96)">
    <rect x="0" y="0" width="520" height="372" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="3"/>
    <path d="M64 0v372M180 0v372M296 0v372M412 0v372M0 88h520M0 186h520M0 284h520" stroke="#e5eef4" stroke-width="4"/>
    <path d="M48 294C116 250 138 144 222 178c68 27 74 112 166 82 47-15 73-56 102-82" fill="none" stroke="{soft}" stroke-width="30" stroke-linecap="round"/>
    <path d="M48 294C116 250 138 144 222 178c68 27 74 112 166 82 47-15 73-56 102-82" fill="none" stroke="{accent}" stroke-width="8" stroke-linecap="round"/>
    <path d="M244 130c0-48 39-87 87-87s87 39 87 87c0 72-87 142-87 142s-87-70-87-142z" fill="{accent}"/>
    <circle cx="331" cy="129" r="31" fill="#ffffff"/>
    <rect x="42" y="38" width="148" height="44" rx="15" fill="#f8fbfd" stroke="#d9e6ed" stroke-width="3"/>
    <text x="62" y="66" fill="#233044" font-family="Arial, Helvetica, sans-serif" font-size="19" font-weight="800">Naver Map</text>
  </g>"""


def shopping_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(535 108)">
    <rect x="0" y="0" width="488" height="356" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="3"/>
    <rect x="64" y="86" width="142" height="190" rx="24" fill="{soft}" stroke="{accent}" stroke-width="5"/>
    <path d="M97 112c0-38 22-62 38-62s38 24 38 62" fill="none" stroke="#233044" stroke-width="8" stroke-linecap="round"/>
    <rect x="272" y="74" width="146" height="202" rx="24" fill="#f8fbfd" stroke="#d9e6ed" stroke-width="5"/>
    <path d="M304 132h82M304 176h64M304 220h92" stroke="{accent}" stroke-width="10" stroke-linecap="round"/>
    <circle cx="292" cy="304" r="17" fill="#172033"/>
    <circle cx="408" cy="304" r="17" fill="#172033"/>
    <path d="M258 296h178" stroke="#172033" stroke-width="8" stroke-linecap="round"/>
  </g>"""


def city_scene(accent: str, soft: str) -> str:
    return f"""
  <g transform="translate(540 112)">
    <rect x="0" y="0" width="466" height="342" rx="28" fill="#ffffff" stroke="#d9e6ed" stroke-width="3"/>
    <path d="M70 260h330" stroke="#d8e4ec" stroke-width="10" stroke-linecap="round"/>
    <path d="M92 104h54v156H92zM174 56h72v204h-72zM278 130h58v130h-58zM360 82h64v178h-64z" fill="#66788d"/>
    <path d="M396 28l28 54h-56z" fill="#53657a"/>
    <circle cx="128" cy="301" r="18" fill="{accent}"/>
    <path d="M190 301h170" stroke="{soft}" stroke-width="14" stroke-linecap="round"/>
    <path d="M190 301h170" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
  </g>"""
