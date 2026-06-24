from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from slugify import slugify

from src.models import ImageAsset


BRAND_TEXT = "Korea Easy Guide"


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
    if any(word in text for word in ("airport", "incheon", "seoul station", "bus", "transport")):
        return "airport"
    if any(word in text for word in ("coupang", "delivery", "shopping", "store", "convenience")):
        return "shopping"
    return "city"


def render_cover(title: str, scene: str) -> str:
    safe_title = escape(title)
    drawing = {
        "ktx": ktx_scene,
        "esim": esim_scene,
        "taxi": taxi_scene,
        "map": map_scene,
        "airport": airport_scene,
        "shopping": shopping_scene,
        "city": city_scene,
    }.get(scene, city_scene)()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="sky" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#eaf6ff"/>
      <stop offset="0.56" stop-color="#fff8ed"/>
      <stop offset="1" stop-color="#e5f7f1"/>
    </linearGradient>
    <linearGradient id="card" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.94"/>
      <stop offset="1" stop-color="#eef6fb" stop-opacity="0.92"/>
    </linearGradient>
    <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="#172033" flood-opacity="0.13"/>
    </filter>
  </defs>
  <rect width="1200" height="675" fill="url(#sky)"/>
  <circle cx="1035" cy="108" r="92" fill="#fff4cf" opacity="0.8"/>
  <path d="M0 505C146 458 273 464 412 497c172 41 319 41 498-14 117-36 215-35 290 1v191H0z" fill="#e9f1f5"/>
  <path d="M0 546c154-28 309-24 462 10 161 36 331 27 507-20 91-24 168-24 231-3v142H0z" fill="#dceaf0"/>
  <g opacity="0.62">
    <path d="M746 245h44v210h-44zM816 197h66v258h-66zM906 278h50v177h-50zM980 156h72v299h-72zM1078 264h48v191h-48z" fill="#66788d"/>
    <path d="M1015 63l39 93h-74z" fill="#53657a"/>
  </g>
  <g filter="url(#softShadow)">
    <rect x="74" y="62" width="1052" height="534" rx="34" fill="url(#card)" stroke="#d7e4ec"/>
  </g>
  {drawing}
  <text x="96" y="556" fill="#172033" font-family="Arial, Helvetica, sans-serif" font-size="34" font-weight="800">{BRAND_TEXT}</text>
</svg>
"""


def ktx_scene() -> str:
    return """
  <g>
    <path d="M145 376c36-75 111-118 224-128l390-34c76-7 145 32 180 99l34 66c15 29-6 63-39 63H164c-22 0-32-39-19-66z" fill="#f8fbfd" stroke="#90a8bb" stroke-width="8"/>
    <path d="M310 276l439-36c61-5 116 25 149 78H253c14-20 32-34 57-42z" fill="#dbeafe"/>
    <path d="M188 408h786" stroke="#2563eb" stroke-width="16" stroke-linecap="round"/>
    <path d="M230 442h714" stroke="#172033" stroke-width="10" stroke-linecap="round" opacity="0.75"/>
    <circle cx="310" cy="466" r="32" fill="#172033"/><circle cx="815" cy="466" r="32" fill="#172033"/>
    <path d="M192 500h830" stroke="#8aa2b4" stroke-width="10" stroke-linecap="round"/>
    <path d="M230 520h720" stroke="#c8d5df" stroke-width="8" stroke-linecap="round"/>
    <text x="186" y="178" fill="#0f766e" font-family="Arial, Helvetica, sans-serif" font-size="52" font-weight="800">KTX</text>
    <text x="186" y="222" fill="#526173" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="700">Tickets and train travel</text>
  </g>"""


def esim_scene() -> str:
    return """
  <g>
    <rect x="188" y="126" width="274" height="410" rx="36" fill="#172033"/>
    <rect x="214" y="168" width="222" height="306" rx="18" fill="#eef8ff"/>
    <circle cx="325" cy="502" r="13" fill="#dbeafe"/>
    <path d="M270 270c36-35 75-35 111 0M292 304c21-20 46-20 67 0M315 337c6-6 15-6 21 0" fill="none" stroke="#2563eb" stroke-width="14" stroke-linecap="round"/>
    <rect x="604" y="154" width="264" height="344" rx="28" fill="#ffffff" stroke="#8aa2b4" stroke-width="8"/>
    <path d="M780 154v74h88" fill="none" stroke="#8aa2b4" stroke-width="8"/>
    <text x="648" y="318" fill="#0f766e" font-family="Arial, Helvetica, sans-serif" font-size="62" font-weight="800">eSIM</text>
    <text x="628" y="374" fill="#526173" font-family="Arial, Helvetica, sans-serif" font-size="25" font-weight="700">Data before arrival</text>
    <path d="M494 332h72" stroke="#b45309" stroke-width="14" stroke-linecap="round"/>
    <path d="M544 296l42 36-42 36" fill="none" stroke="#b45309" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  </g>"""


def taxi_scene() -> str:
    return """
  <g>
    <rect x="170" y="205" width="270" height="330" rx="34" fill="#172033"/>
    <rect x="196" y="250" width="218" height="218" rx="20" fill="#f7fbfd"/>
    <circle cx="305" cy="494" r="12" fill="#dbeafe"/>
    <rect x="246" y="297" width="118" height="58" rx="18" fill="#fee08a"/>
    <text x="273" y="337" fill="#172033" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="800">T</text>
    <path d="M546 353l57-86h223l72 86h36c33 0 60 27 60 60v43H508v-43c0-33 27-60 60-60z" fill="#facc15" stroke="#172033" stroke-width="8"/>
    <path d="M620 289h184l42 64H578z" fill="#e0f2fe" stroke="#172033" stroke-width="7"/>
    <circle cx="620" cy="463" r="42" fill="#172033"/><circle cx="881" cy="463" r="42" fill="#172033"/>
    <circle cx="620" cy="463" r="17" fill="#cbd5df"/><circle cx="881" cy="463" r="17" fill="#cbd5df"/>
    <rect x="673" y="229" width="106" height="44" rx="14" fill="#172033"/>
    <text x="687" y="260" fill="#ffffff" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="800">TAXI</text>
    <text x="548" y="178" fill="#0f766e" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="800">Kakao T Taxi</text>
  </g>"""


def map_scene() -> str:
    return """
  <g>
    <rect x="162" y="128" width="778" height="394" rx="30" fill="#ffffff" stroke="#d7e4ec" stroke-width="8"/>
    <path d="M236 128v394M392 128v394M548 128v394M704 128v394M162 226h778M162 324h778M162 422h778" stroke="#dbe7ef" stroke-width="7"/>
    <path d="M192 463C313 390 370 257 488 302c93 35 96 154 226 110 75-26 121-98 205-94" fill="none" stroke="#0f766e" stroke-width="18" stroke-linecap="round"/>
    <path d="M512 242c0-68 55-123 123-123s123 55 123 123c0 96-123 192-123 192S512 338 512 242z" fill="#ef4444"/>
    <circle cx="635" cy="242" r="45" fill="#ffffff"/>
    <text x="200" y="182" fill="#2563eb" font-family="Arial, Helvetica, sans-serif" font-size="36" font-weight="800">NAVER MAP</text>
    <rect x="774" y="454" width="104" height="34" rx="17" fill="#172033" opacity="0.84"/>
  </g>"""


def airport_scene() -> str:
    return """
  <g>
    <path d="M170 403h830" stroke="#8aa2b4" stroke-width="12" stroke-linecap="round"/>
    <path d="M224 433h720" stroke="#cbd5df" stroke-width="9" stroke-linecap="round"/>
    <path d="M240 330l326-114 239 39c29 5 55 22 71 47l44 68-397-25-205 83c-38 15-78-20-65-59z" fill="#f8fbfd" stroke="#60758a" stroke-width="8"/>
    <path d="M536 228l78-92h84l-43 111" fill="#dbeafe" stroke="#60758a" stroke-width="8" stroke-linejoin="round"/>
    <path d="M797 259l105-70h74l-67 106" fill="#e0f2fe" stroke="#60758a" stroke-width="8" stroke-linejoin="round"/>
    <circle cx="445" cy="405" r="28" fill="#172033"/><circle cx="803" cy="405" r="28" fill="#172033"/>
    <rect x="186" y="159" width="240" height="96" rx="20" fill="#ffffff" stroke="#d7e4ec" stroke-width="7"/>
    <text x="214" y="199" fill="#0f766e" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="800">ICN → Seoul</text>
    <text x="214" y="232" fill="#526173" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700">Airport transfer</text>
  </g>"""


def shopping_scene() -> str:
    return """
  <g>
    <rect x="190" y="188" width="270" height="270" rx="28" fill="#ffffff" stroke="#d7e4ec" stroke-width="8"/>
    <path d="M252 258c0-52 33-86 73-86s73 34 73 86" fill="none" stroke="#0f766e" stroke-width="16" stroke-linecap="round"/>
    <path d="M222 262h206l-22 196H244z" fill="#dbeafe" stroke="#2563eb" stroke-width="8"/>
    <rect x="604" y="176" width="280" height="266" rx="26" fill="#fff7ed" stroke="#f59e0b" stroke-width="8"/>
    <path d="M646 248h196M646 310h156M646 372h116" stroke="#b45309" stroke-width="18" stroke-linecap="round"/>
    <circle cx="900" cy="454" r="38" fill="#172033"/><circle cx="645" cy="454" r="38" fill="#172033"/>
    <path d="M574 444h380" stroke="#172033" stroke-width="12" stroke-linecap="round"/>
    <text x="588" y="134" fill="#0f766e" font-family="Arial, Helvetica, sans-serif" font-size="36" font-weight="800">Shopping & Daily Life</text>
  </g>"""


def city_scene() -> str:
    return """
  <g>
    <path d="M628 286h44v170h-44zM694 234h62v222h-62zM782 274h44v182h-44zM854 196h78v260h-78zM958 270h54v186h-54z" fill="#60758a"/>
    <path d="M888 116l44 80h-78z" fill="#51677c"/>
    <circle cx="250" cy="292" r="42" fill="#263243"/>
    <path d="M194 374c17-58 95-58 112 0l30 168H164z" fill="#0f766e"/>
    <rect x="354" y="421" width="92" height="124" rx="12" fill="#64748b"/>
    <rect x="374" y="390" width="52" height="42" rx="12" fill="none" stroke="#475569" stroke-width="9"/>
    <path d="M96 100h430M96 206h430M96 312h430" stroke="#d7e5eb" stroke-width="9"/>
    <path d="M206 82v354M348 82v354" stroke="#d7e5eb" stroke-width="9"/>
  </g>"""
