from __future__ import annotations

from dataclasses import asdict, dataclass
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
    style = (
        "premium editorial travel-guide photography, realistic but clean, bright natural light, "
        "modern Korean urban environment, useful visual information, no text overlays, no logos, "
        "no distorted UI, no fake brand marks, no watermark, sharp composition, professional blog header"
    )

    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} visual guide for foreign visitors in Korea",
        caption="A practical visual guide for planning this part of your Korea trip.",
        prompt=(
            f"Create a 16:9 hero image for an English Korea travel guide article titled '{title}'. "
            f"Main subject: {visual_subject}. Audience: foreign tourists, exchange students, and long-stay visitors. "
            f"Style: {style}. Composition should leave calm negative space and feel trustworthy, practical, "
            "and current rather than cartoonish."
        ),
    )
    inline_checklist = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Visual checklist for {candidate.keyword} in Korea",
        caption="Use the visual checklist to avoid common mistakes before relying on the service.",
        prompt=(
            f"Create a premium 16:9 illustrated checklist for a Korea travel guide about '{candidate.keyword}'. "
            f"Show the key process visually: {_inline_subject(scene)}. "
            "Use a modern soft 3D/editorial illustration style with icons, cards, and clear visual flow. "
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
    hero_subject = _windows_hero_subject(topic_scene)
    inline_subject = _windows_inline_subject(topic_scene)
    palette = _windows_palette(topic_scene)
    hero_style = _windows_hero_style(topic_scene)
    hero_framing = _windows_hero_framing(topic_scene)
    inline_style = _windows_inline_style(topic_scene)
    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} beginner-friendly Windows help visual",
        caption="A realistic beginner-friendly visual for solving this Windows problem safely.",
        prompt=(
            f"Use case: {hero_style}. "
            f"Create a realistic 16:9 hero image for an English beginner computer help article titled '{title}'. "
            f"Primary request: help a non-technical reader understand a safe first-step fix for {candidate.keyword}. "
            f"Scene/backdrop: {hero_subject}. "
            "Use blank cards, abstract lines, and icon-like shapes instead of any readable interface. "
            f"Composition/framing: {hero_framing}. "
            f"Lighting/mood: bright natural daylight, calm, reassuring, practical. Color palette: {palette}. "
            "Do not show real Microsoft logos, fake Windows UI, readable error codes, readable letters or numbers, brand marks, "
            "private information, warning screens, command prompts, registry editors, or text overlays. "
            "Avoid fake support documents, fake screenshots, scary alert dialogs, distorted hands, extra fingers, watermarks, and cartoon/vector art. "
            "Style diversity rule: avoid repeating the same laptop-on-white-desk composition across multiple Windows Update posts."
        ),
    )
    inline = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Safe step-by-step troubleshooting setup for {candidate.keyword}",
        caption="Work through the safe checks first before trying advanced repair steps.",
        prompt=(
            f"Use case: {inline_style}. "
            f"Create a clean 16:9 in-article illustration for a beginner Windows troubleshooting guide about '{candidate.keyword}'. "
            f"Primary request: visually support the step-by-step safe checks before advanced fixes. Concept: {inline_subject}. "
            "Use a visually distinct style from the hero image and from other Windows Update subtopics. "
            "Show the troubleshooting flow with abstract symbols such as restart arrows, checklist cards, clock, shield, "
            "repair gear, Wi-Fi waves, speaker waves, folder shapes, or device outlines when relevant. "
            f"Color palette: {palette}. "
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
