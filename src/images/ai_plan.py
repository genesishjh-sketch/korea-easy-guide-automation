from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path

from src.images.cover import detect_scene
from src.models import ImageAsset, TopicCandidate


@dataclass(frozen=True)
class PlannedImage:
    role: str
    filename: str
    alt: str
    caption: str
    prompt: str
    required: bool = True

    @property
    def url(self) -> str:
        return f"assets/{self.filename}"


@dataclass(frozen=True)
class ArticleImagePlan:
    mode: str
    strict: bool
    notes: list[str]
    images: list[PlannedImage]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "strict": self.strict,
            "notes": self.notes,
            "images": [asdict(image) | {"url": image.url} for image in self.images],
        }

    def hero_asset(self, article_dir: Path | None = None) -> ImageAsset:
        image = self.images[0]
        return _asset_from_plan(image, article_dir)

    def inline_assets(self, article_dir: Path | None = None) -> list[ImageAsset]:
        return [_asset_from_plan(image, article_dir) for image in self.images[1:]]


def build_article_image_plan(candidate: TopicCandidate, title: str) -> ArticleImagePlan:
    if candidate.category in {
        "Windows Update",
        "Wi-Fi & Internet",
        "Bluetooth & Devices",
        "Sound & Microphone",
        "Printer & Scanner",
        "Boot & Recovery",
        "File Explorer",
        "Windows Search",
        "OneDrive & Account",
        "Apps & Settings",
        "Beginner PC Tips",
        "Error Codes",
        "Computer Help",
    }:
        return build_windows_image_plan(candidate, title)

    extension = "jpg"
    scene = detect_scene(f"{candidate.keyword} {title}")
    visual_subject = _visual_subject(scene, candidate.keyword)
    hero_brief = _korea_visual_brief(f"{candidate.keyword} {title}", scene, "hero")
    inline_brief = _korea_visual_brief(f"{candidate.keyword} {title}", scene, "inline")

    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} visual guide for foreign visitors in Korea",
        caption="A practical visual guide for planning this part of your Korea trip.",
        prompt=(
            f"Create a 16:9 hero image for an English Korea travel guide article titled '{title}'. "
            f"Main subject: {visual_subject}. Audience: foreign tourists, exchange students, and long-stay visitors. "
            f"Visual brief: {hero_brief['brief']}. Composition/framing: {hero_brief['framing']}. "
            f"Material/camera direction: {hero_brief['medium']}. Distinctive props: {hero_brief['props']}. "
            f"Lighting/mood: {hero_brief['mood']}. Accent color: {hero_brief['accent']}. "
            "Fresh prompt rule: this is a creative brief, not a reusable prompt; write a new one-off image prompt for this article. "
            "No text overlays, no readable app screens, no logos, no fake brand marks, no private information, no watermark. "
            "Avoid repeating the same traveler-with-phone composition across nearby Korea posts."
        ),
    )
    inline_checklist = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Visual checklist for {candidate.keyword} in Korea",
        caption="Use the visual checklist to avoid common mistakes before relying on the service.",
        prompt=(
            f"Create a premium 16:9 illustrated checklist for a Korea travel guide about '{candidate.keyword}'. "
            f"Show the key process visually: {_inline_subject(scene)}. Visual brief: {inline_brief['brief']}. "
            f"Composition/framing: {inline_brief['framing']}. Material/camera direction: {inline_brief['medium']}. "
            f"Distinctive props: {inline_brief['props']}. Accent color: {inline_brief['accent']}. "
            "Fresh prompt rule: create a new visual idea for this article instead of reusing a previous prompt, camera setup, or prop layout. "
            "No readable text, no Korean letters, no logos, no fake app UI, no private information, and no watermarks."
        ),
    )

    return ArticleImagePlan(
        mode="codex_generated_no_api",
        strict=True,
        notes=[
            "Do not call paid image APIs in the Python pipeline.",
            "Use Codex-generated JPG assets from src/images/ai_assets/korea.",
            "Default Korea image roles are hero photo plus one information-rich checklist/flow image.",
            "Only add a third or fourth image when it has a distinct role such as comparison, map flow, warning, or cost decision.",
            "Do not add multiple similar lifestyle/photos just to increase image count.",
            "Publishing should stop when required image files are missing.",
        ],
        images=[hero, inline_checklist],
    )


def build_windows_image_plan(candidate: TopicCandidate, title: str) -> ArticleImagePlan:
    extension = "jpg"
    topic_scene = _windows_topic_scene(candidate.keyword, title)
    text = f"{candidate.keyword} {title}"
    hero_brief = _windows_visual_brief(text, topic_scene, "hero")
    inline_brief = _windows_visual_brief(text, topic_scene, "inline")
    palette = _windows_palette(topic_scene)
    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} beginner-friendly Windows help visual",
        caption="A realistic beginner-friendly visual for solving this Windows problem safely.",
        prompt=(
            f"Use case: {hero_brief['use_case']}. "
            f"Create a realistic 16:9 hero image for an English beginner computer help article titled '{title}'. "
            f"Primary request: help a non-technical reader understand a safe first-step fix for {candidate.keyword}. "
            f"Visual brief: {hero_brief['brief']}. "
            f"Composition/framing: {hero_brief['framing']}. "
            f"Material/camera direction: {hero_brief['medium']}. "
            f"Distinctive props: {hero_brief['props']}. "
            f"Lighting/mood: {hero_brief['mood']}. Color palette: {palette}; accent color: {hero_brief['accent']}. "
            "Fresh prompt rule: this is a creative brief, not a reusable prompt; write a new one-off image prompt for this article. "
            "Do not show real Microsoft logos, fake Windows UI, readable error codes, readable letters or numbers, brand marks, "
            "private information, warning screens, command prompts, registry editors, or text overlays. "
            "Avoid fake support documents, fake screenshots, scary alert dialogs, distorted hands, extra fingers, watermarks, and generic stock-photo office scenes. "
            "Do not reuse the same laptop-on-bright-desk composition from nearby posts."
        ),
    )
    inline = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Safe step-by-step troubleshooting setup for {candidate.keyword}",
        caption="Work through the safe checks first before trying advanced repair steps.",
        prompt=(
            f"Use case: {inline_brief['use_case']}. "
            f"Create a clean 16:9 in-article illustration for a beginner Windows troubleshooting guide about '{candidate.keyword}'. "
            f"Primary request: visually support the step-by-step safe checks before advanced fixes. Visual brief: {inline_brief['brief']}. "
            f"Composition/framing: {inline_brief['framing']}. "
            f"Material/camera direction: {inline_brief['medium']}. "
            f"Distinctive props: {inline_brief['props']}. "
            "Fresh prompt rule: create a new visual idea for this article instead of reusing a previous prompt, camera setup, or prop layout. "
            f"Color palette: {palette}; accent color: {inline_brief['accent']}. "
            "No real or fake operating-system screens, Microsoft logos, readable UI text, error codes, scary warning overlays, "
            "command prompts, registry editors, fake official documentation, watermarks, or brand marks."
        ),
    )
    return ArticleImagePlan(
        mode="codex_generated_no_api",
        strict=True,
        notes=[
            "Do not call paid image APIs in the Python pipeline.",
            "Use Codex-generated JPG assets from src/images/ai_assets/windows.",
            "Do not use SVG fallback for Windows help public posts.",
            "Do not generate fake Windows UI or readable error screens.",
            "Vary visual concepts across posts: change medium, camera angle, props, composition, and dominant accent color by article type.",
            "Hero and inline images must have different roles and should not look like two versions of the same template.",
            "The saved image plan is only a creative brief; Codex image generation must use a fresh article-specific prompt instead of pasting a fixed formula.",
            "Do not add extra images unless each image has a distinct role such as hero, troubleshooting flow, warning, or decision checklist.",
            "Publishing should stop when required image files are missing.",
        ],
        images=[hero, inline],
    )


def _asset_from_plan(image: PlannedImage, article_dir: Path | None) -> ImageAsset:
    path = image.url if article_dir is None else str(article_dir / image.url)
    return ImageAsset(
        path=path,
        url=image.url,
        alt=image.alt,
        source="codex_image_plan",
        credit="Generated with Codex image generation",
        caption=image.caption,
    )


def _planned_image_extension() -> str:
    mode = os.getenv("IMAGE_ASSET_MODE", "").strip().lower()
    if mode in {"jpg", "jpeg", "raster", "codex_jpg", "manual_jpg"}:
        return "jpg"
    return "svg"


def _visual_subject(scene: str, keyword: str) -> str:
    subjects = {
        "airport": "a foreign traveler choosing between airport train, bus, and taxi options at Incheon Airport",
        "ktx": "a traveler preparing to board a modern KTX train at a Korean rail station",
        "esim": "a traveler setting up mobile data on a smartphone after arriving in Korea",
        "taxi": "a visitor confirming a taxi pickup point on a city street in Seoul",
        "map": "a traveler using a navigation app while walking near a Seoul subway exit",
        "transport_card": "a foreign visitor using a generic prepaid transit card at a Seoul subway gate",
        "shopping": "a visitor using everyday Korean services such as convenience stores, delivery, or shopping",
    }
    return subjects.get(scene, f"a practical Korea travel scene related to {keyword}")


def _inline_subject(scene: str) -> str:
    subjects = {
        "airport": "checking train and bus signs in an airport arrival hall",
        "ktx": "checking a train platform and ticket details before boarding",
        "esim": "activating mobile data while keeping passport and travel documents nearby",
        "taxi": "standing at a safe pickup point and matching the taxi information",
        "map": "comparing walking and subway directions near a station exit",
        "transport_card": "buying, recharging, and tapping a generic transit card at a subway station or convenience store",
        "shopping": "using a self-service kiosk or payment counter in a clean everyday setting",
    }
    return subjects.get(scene, "following the key step clearly and safely")


def _inline_caption(scene: str) -> str:
    captions = {
        "airport": "Check your route before leaving the arrival area, especially if you have luggage.",
        "ktx": "Confirm your station, train number, platform, and departure time before boarding.",
        "esim": "Set up mobile data before relying on maps, taxi apps, or translation tools.",
        "taxi": "Confirm the pickup point and destination before the taxi arrives.",
        "map": "Use Korean map apps to check walking, subway, and bus routes before moving.",
        "transport_card": "Recharge the card before you rely on subway or bus transfers.",
        "shopping": "Check payment options and app requirements before depending on a local service.",
    }
    return captions.get(scene, "Use the visual checklist to make the process easier in Korea.")


def _windows_topic_scene(keyword: str, title: str) -> str:
    text = f"{keyword} {title}".lower()
    if any(token in text for token in ["disconnect", "disconnecting", "keeps disconnecting", "drops", "dropping"]):
        return "network_wifi_disconnect"
    if any(token in text for token in ["cannot connect", "can't connect", "can not connect", "not connect to this network"]):
        return "network_cannot_connect"
    if any(token in text for token in ["adapter missing", "network adapter missing", "wireless adapter missing"]):
        return "network_adapter_missing"
    if any(token in text for token in ["dns", "server not responding"]):
        return "network_dns"
    if any(token in text for token in ["wi-fi", "wifi", "internet", "network"]):
        return "network"
    if "bluetooth" in text or "device" in text:
        return "device"
    if any(token in text for token in ["sound", "audio", "microphone", "mic"]):
        return "audio"
    if any(token in text for token in ["printer", "scanner"]):
        return "printer"
    if any(token in text for token in ["onedrive", "account", "sign in", "sync"]):
        return "account"
    if any(token in text for token in ["search", "file explorer", "folder", "explorer"]):
        return "files"
    if any(token in text for token in ["boot", "startup", "recovery", "repair"]):
        return "recovery"
    if any(token in text for token in ["download stuck", "stuck at 0", "stuck at 0%", "stuck downloading"]):
        return "update_download"
    if any(token in text for token in ["cleanup", "clean up", "disk cleanup", "storage sense"]):
        return "update_cleanup"
    if any(token in text for token in ["0x", "error code", "install error", "update error"]):
        return "update_error_code"
    if any(token in text for token in ["pending restart", "restart stuck", "restart required"]):
        return "update_restart"
    if any(token in text for token in ["update", "restart"]):
        return "update"
    return "general"


def _windows_visual_brief(text: str, scene: str, role: str) -> dict[str, str]:
    scene_briefs = {
        "network_wifi_disconnect": "home connectivity drops in and out, shown as an interrupted signal between a router and a personal device",
        "network_cannot_connect": "a failed connection attempt, shown as two devices separated by an unfinished path",
        "network_adapter_missing": "missing or unavailable network hardware, shown through adapter, cable, and safe inspection props",
        "network_dns": "DNS lookup or routing failure, shown as abstract network nodes and a paused path",
        "network": "basic home internet troubleshooting with router, device, and safe restart/checklist cues",
        "device": "safe peripheral troubleshooting without showing real device manager screens",
        "audio": "microphone or speaker troubleshooting using sound-wave and hardware props",
        "printer": "printer queue or printer connection troubleshooting using paper path and cable cues",
        "account": "account or sync troubleshooting using privacy-safe cloud and notebook metaphors",
        "files": "file search or folder organization troubleshooting using folder-card and magnifier cues",
        "recovery": "safe startup or recovery troubleshooting with backup-first visual cues",
        "update_download": "an update download that is waiting or paused, shown without fake progress UI",
        "update_cleanup": "storage cleanup and safe removal decisions using storage blocks and checklist cues",
        "update_error_code": "error-code troubleshooting as a diagnostic puzzle without readable code text",
        "update_restart": "restart or pending-restart troubleshooting using clock and power-cycle metaphors",
        "update": "general update troubleshooting with shield, checklist, and repair symbols",
        "general": "beginner computer help with safe, calm troubleshooting cues",
    }
    use_cases = {
        "hero": [
            "photorealistic-natural",
            "stylized-concept",
            "product-mockup",
            "scientific-educational",
        ],
        "inline": [
            "infographic-diagram",
            "stylized-concept",
            "productivity-visual",
            "scientific-educational",
        ],
    }
    media = {
        "hero": [
            "low-angle macro photo with one foreground object in sharp focus",
            "top-down editorial flat lay with physical cards and device props",
            "miniature tabletop model made from matte paper and soft plastic",
            "real home troubleshooting scene with warm practical lighting",
            "dark repair-bench close-up with controlled rim light",
        ],
        "inline": [
            "clean 3D diagram made from unlabeled cards, arrows, and simple objects",
            "paper cutout flow on a desk, photographed from above",
            "abstract glass-node network map with no letters or numbers",
            "step-by-step object arrangement using three distinct physical zones",
            "soft isometric educational illustration rendered as premium bitmap art",
        ],
    }
    framings = [
        "strong asymmetrical composition with the main object away from the center",
        "diagonal left-to-right flow with clear depth and generous negative space",
        "tight crop that avoids the generic full laptop-on-desk look",
        "wide scene with one unusual foreground prop and a blurred secondary device",
        "top-down layout with separated zones for problem, check, and safe next step",
    ]
    props = {
        "network_wifi_disconnect": [
            "router light, interrupted Wi-Fi arcs, couch-side laptop, lamp glow",
            "phone, router, blank sticky notes, fading signal beads",
            "two-room connection path, soft shadows, disconnected blue segments",
        ],
        "network_cannot_connect": [
            "miniature blocks, broken bridge of dots, laptop-shaped tile, router-shaped tile",
            "two blank device cards, unfinished cable path, one coral marker",
            "separated islands on a tabletop map with a gap in the connection route",
        ],
        "network_adapter_missing": [
            "USB network adapter, Ethernet cable connector, parts tray, anti-static mat",
            "adapter silhouette card, cable loop, small screwdriver, blank checklist",
            "close-up port, unplugged cable, hardware tray, soft cyan highlight",
        ],
        "network_dns": [
            "translucent nodes, server-block shapes, paused amber routing point",
            "branching light paths, blank node cards, deep navy background",
            "network map sculpture, one stopped path, soft glow without text",
        ],
    }
    fallback_props = [
        "blank checklist cards, shield object, restart arrow shape, notebook",
        "physical cards, cable, clock, small repair gear, neutral laptop edge",
        "abstract blocks, safe-step tokens, magnifier, soft device outline",
    ]
    accents = ["cyan", "teal", "amber", "coral", "green", "violet", "steel blue"]
    moods = [
        "bright natural daylight, calm, reassuring, practical",
        "warm evening home light with restrained cool technical accents",
        "clean studio light, quiet, precise, and beginner-friendly",
        "low-key technical lighting, focused but not alarming",
    ]

    return {
        "use_case": _pick(use_cases[role], text, role, "use_case"),
        "brief": scene_briefs.get(scene, scene_briefs["general"]),
        "medium": _pick(media[role], text, role, "medium"),
        "framing": _pick(framings, text, role, "framing"),
        "props": _pick(props.get(scene, fallback_props), text, role, "props"),
        "accent": _pick(accents, text, role, "accent"),
        "mood": _pick(moods, text, role, "mood"),
    }


def _korea_visual_brief(text: str, scene: str, role: str) -> dict[str, str]:
    scene_briefs = {
        "airport": "arrival-day movement through airport, rail, bus, luggage, and decision points",
        "ktx": "intercity rail planning with station, platform, ticket-check, and luggage cues",
        "esim": "mobile-data setup for a traveler without showing fake app screens",
        "taxi": "safe pickup and destination confirmation for a visitor in Korea",
        "map": "route choice and navigation in a Korean city without readable app UI",
        "transport_card": "transit-card purchase, recharge, and gate-tap flow",
        "shopping": "everyday local service use such as convenience store, delivery, or payment counter",
        "general": "practical Korea travel preparation for a first-time visitor",
    }
    media = {
        "hero": [
            "realistic editorial travel photography with human presence but no readable screens",
            "cinematic street-level photo with one clear practical action",
            "top-down travel flat lay with tickets, phone, card, and luggage objects",
            "wide environmental scene with signage blurred into abstract shapes",
            "premium 3D editorial scene using realistic travel props",
        ],
        "inline": [
            "clean 3D process diagram with unlabeled cards and route objects",
            "paper-map style visual flow photographed from above",
            "object-based checklist scene with three separate practical zones",
            "soft isometric travel-service diagram rendered as bitmap art",
            "comparison board using physical props rather than readable text",
        ],
    }
    framings = [
        "strong foreground object, human/traveler element secondary, generous negative space",
        "diagonal movement from preparation to action, with clear depth",
        "top-down layout that separates before, during, and after steps",
        "tight crop on the useful object rather than a generic skyline or tourist pose",
        "wide scene that hints at place while keeping the action readable",
    ]
    props = {
        "airport": ["carry-on luggage, transit-card shape, platform gate, abstract route line", "arrival hall floor, suitcase wheel, train/bus choice tokens", "passport cover without details, luggage tag, blank route cards"],
        "ktx": ["train platform edge, ticket-like blank card, small suitcase, seat/clock symbols", "station bench, rail line diagram made of blank cards, luggage handle", "platform floor markings, suitcase, generic train silhouette"],
        "esim": ["phone with blank screen, SIM tray pin, passport cover without details, signal token", "travel documents with no readable text, phone, small setup cards", "airport cafe table, blank phone, signal sculpture"],
        "taxi": ["curbside pickup marker without text, phone blank screen, car door detail, suitcase", "street corner, luggage handle, destination pin object, blank confirmation card", "night curb scene, soft taxi-like car silhouette without logos"],
        "map": ["folded paper map, subway-exit-like shape with no text, phone blank screen", "walking route tokens, station-stair object, blank direction cards", "city block model, route line, destination pin object"],
    }
    fallback_props = [
        "phone with blank screen, blank checklist cards, luggage, payment-card shape",
        "route-line tokens, small suitcase, neutral city props, blank cards",
        "travel-object flat lay with no readable labels",
    ]
    accents = ["sky blue", "teal", "signal green", "warm yellow", "coral", "rail blue", "mint"]
    moods = [
        "bright natural daylight, practical, clean, and current",
        "soft evening city light, calm and helpful",
        "clear indoor travel-service lighting, trustworthy and uncluttered",
        "fresh morning travel-prep mood with realistic shadows",
    ]
    return {
        "brief": scene_briefs.get(scene, scene_briefs["general"]),
        "medium": _pick(media[role], text, role, "korea-medium"),
        "framing": _pick(framings, text, role, "korea-framing"),
        "props": _pick(props.get(scene, fallback_props), text, role, "korea-props"),
        "accent": _pick(accents, text, role, "korea-accent"),
        "mood": _pick(moods, text, role, "korea-mood"),
    }


def _pick(options: list[str], text: str, *salt: str) -> str:
    digest = hashlib.sha256("|".join((*salt, text)).encode("utf-8")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _windows_hero_subject(scene: str) -> str:
    subjects = {
        "network": "a clean home desk with a laptop, router silhouette, soft Wi-Fi wave symbols, and a simple paper checklist",
        "device": "a tidy desk with a laptop, generic wireless earbuds or mouse, connection symbols, and a beginner checklist",
        "audio": "a laptop beside generic headphones and a small microphone, with abstract sound-wave symbols and a safe checklist",
        "printer": "a small home office desk with a generic printer shape, laptop, cable, and abstract repair checklist symbols",
        "account": "a laptop next to a notebook and cloud-shaped abstract sync symbols, with calm privacy-focused desk styling",
        "files": "a laptop with blank folder-shaped cards, magnifying glass, and tidy file organization props",
        "recovery": "a calm repair desk with a laptop, backup drive, shield symbol, and step-by-step safety checklist cards",
        "update_download": "a home laptop beside a router silhouette and a paused progress concept made from blank geometric blocks, with a calm checklist notebook nearby",
        "update_cleanup": "a tidy desk with a laptop, storage drive, recycle-bin-shaped abstract container, and neat cleanup checklist cards",
        "update_error_code": "a laptop on a repair desk with abstract puzzle pieces, shield symbol, and non-readable diagnostic cards arranged like a problem-solving workspace",
        "update_restart": "a laptop beside a clock, circular restart arrows, and a simple power button symbol, arranged as a calm waiting-and-restart concept",
        "update": "a clean home desk with a laptop displaying only abstract update, checklist, shield, and repair symbols",
        "general": "a clean home desk with a laptop, notebook, abstract checklist cards, shield, and repair symbols",
    }
    return subjects.get(scene, subjects["general"])


def _windows_hero_style(scene: str) -> str:
    styles = {
        "network": "photorealistic home connectivity scene with router and laptop",
        "device": "photorealistic peripheral setup scene with hands-free device props",
        "audio": "photorealistic audio workspace scene with headphones and microphone props",
        "printer": "photorealistic home-office printer troubleshooting scene",
        "account": "privacy-focused editorial desk photo with cloud-sync metaphors",
        "files": "organized file-management editorial flat-lay photo",
        "recovery": "cautious repair-prep editorial photo with backup-drive emphasis",
        "update_download": "photorealistic network-and-waiting scene with paused-progress metaphor",
        "update_cleanup": "top-down storage cleanup flat-lay photo with backup and organization props",
        "update_error_code": "cinematic diagnostic workbench photo with puzzle and investigation metaphors",
        "update_restart": "photorealistic waiting-and-restart scene with clock and power-cycle metaphors",
        "update": "photorealistic Windows update help scene with abstract update symbols",
        "general": "photorealistic beginner computer help scene",
    }
    return styles.get(scene, styles["general"])


def _windows_hero_framing(scene: str) -> str:
    framings = {
        "network": "horizontal 16:9, router in soft foreground, laptop offset to one side, visible home workspace depth",
        "device": "horizontal 16:9, close desk-level angle with device props separated from the laptop",
        "audio": "horizontal 16:9, close-up of headphones and microphone beside a softly blurred laptop",
        "printer": "horizontal 16:9, wider home-office view with printer as the main object and laptop secondary",
        "account": "horizontal 16:9, calm privacy-focused desk arrangement with cloud-shaped abstract props",
        "files": "horizontal 16:9, top-down organized flat-lay with folder cards and magnifying glass",
        "recovery": "horizontal 16:9, backup drive prominent in foreground, laptop and safety props behind",
        "update_download": "horizontal 16:9, router and paused-progress metaphor visible, laptop angled away from center",
        "update_cleanup": "horizontal 16:9, top-down flat-lay with storage drive, file boxes, cleanup tray, and laptop edge",
        "update_error_code": "horizontal 16:9, lower-key diagnostic workbench composition with puzzle pieces in foreground",
        "update_restart": "horizontal 16:9, clock and power-cycle object prominent, laptop secondary, patient waiting composition",
        "update": "horizontal 16:9, uncluttered desk-level editorial photo, clear foreground subject, generous negative space",
        "general": "horizontal 16:9, practical desk-level editorial photo with clear subject separation",
    }
    return framings.get(scene, framings["general"])


def _windows_inline_subject(scene: str) -> str:
    subjects = {
        "network": "a beginner-friendly desk scene showing a router, laptop, restart arrow, Wi-Fi waves, and a three-step blank checklist",
        "device": "a simple connection-check scene with a laptop, generic device outline, restart arrow, and blank troubleshooting cards",
        "audio": "a calm audio-check scene with headphones, microphone shape, volume wave icons, and blank checklist cards",
        "printer": "a home printer troubleshooting scene with cable, printer outline, clock icon, and blank step cards",
        "account": "a privacy-safe sync-check scene with cloud icons, shield icon, clock icon, and blank checklist cards",
        "files": "a file search help scene with folder cards, magnifying glass, restart arrow, and blank checklist cards",
        "recovery": "a cautious repair-prep scene with backup drive, shield, clock, and blank step cards for safe recovery order",
        "update_download": "a download troubleshooting flow with a paused progress symbol, network waves, clock, restart arrow, and blank step cards",
        "update_cleanup": "a safe cleanup decision flow with storage blocks, broom-like abstract shape, shield, recycle container, and blank step cards",
        "update_error_code": "an error-code troubleshooting flow with puzzle pieces, shield, magnifying glass, repair gear, and blank decision cards",
        "update_restart": "a restart troubleshooting flow with circular arrows, clock, power symbol, shield, and blank safe-order cards",
        "update": "an update repair flow with restart arrows, clock, shield, repair gear, and blank checklist cards",
        "general": "a simple safe troubleshooting flow with restart arrow, checklist, clock, shield, and repair gear symbols",
    }
    return subjects.get(scene, subjects["general"])


def _windows_inline_style(scene: str) -> str:
    styles = {
        "network": "isometric connectivity map illustration",
        "device": "modular device-pairing card illustration",
        "audio": "sound-wave troubleshooting board illustration",
        "printer": "paper-path and queue-flow illustration",
        "account": "privacy-safe account sync decision diagram",
        "files": "folder organization flow illustration",
        "recovery": "safety-first repair ladder illustration",
        "update_download": "timeline-style network troubleshooting diagram",
        "update_cleanup": "storage decision board with backup-first visual flow",
        "update_error_code": "diagnostic decision tree with puzzle-piece investigation theme",
        "update_restart": "restart sequence timeline with clock and power-cycle stages",
        "update": "friendly illustrated troubleshooting infographic",
        "general": "friendly illustrated troubleshooting infographic",
    }
    return styles.get(scene, styles["general"])


def _windows_palette(scene: str) -> str:
    palettes = {
        "network": "clean whites, soft teal accents, muted graphite, and light desk wood",
        "device": "clean whites, muted blue accents, graphite, and soft gray",
        "audio": "clean whites, soft green accents, graphite, and warm neutral desk tones",
        "printer": "clean whites, muted cyan accents, graphite, and light gray",
        "account": "clean whites, soft sky-blue accents, graphite, and gentle warm neutrals",
        "files": "clean whites, muted amber accents, graphite, and pale gray",
        "recovery": "clean whites, restrained red caution accent, graphite, and calm neutral tones",
        "update_download": "clean whites, soft teal-blue accents, graphite, and pale desk wood",
        "update_cleanup": "clean whites, fresh green accents, graphite, and light warm neutral tones",
        "update_error_code": "clean whites, muted indigo accents, graphite, and soft gray repair-desk tones",
        "update_restart": "clean whites, soft violet-blue accents, graphite, and calm neutral tones",
        "update": "clean whites, soft blue accents, graphite, and light desk wood",
        "general": "clean whites, soft blue-green accents, graphite, and calm neutral tones",
    }
    return palettes.get(scene, palettes["general"])
