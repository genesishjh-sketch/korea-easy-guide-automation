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

    extension = _planned_image_extension()
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
    inline = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Step-by-step example for {candidate.keyword} in Korea",
        caption=_inline_caption(scene),
        prompt=(
            f"Create a realistic 16:9 in-article image for a Korea travel guide about '{candidate.keyword}'. "
            f"Show a practical step in the process: {_inline_subject(scene)}. "
            "Make it look like an authentic travel help image, with clear environment details, natural colors, "
            "no readable private information, no text overlays, no watermarks, and no fake app screens."
        ),
    )

    return ArticleImagePlan(
        mode="codex_generated_no_api",
        strict=True,
        notes=[
            "Do not call paid image APIs in the Python pipeline.",
            "Generate these assets manually with Codex image generation, or use local SVG fallback in CI.",
            "Publishing should stop when required image files are missing.",
        ],
        images=[hero, inline],
    )


def build_windows_image_plan(candidate: TopicCandidate, title: str) -> ArticleImagePlan:
    extension = _planned_image_extension()
    topic_scene = _windows_topic_scene(candidate.keyword, title)
    hero_subject = _windows_hero_subject(topic_scene)
    inline_subject = _windows_inline_subject(topic_scene)
    palette = _windows_palette(topic_scene)
    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} beginner-friendly Windows help visual",
        caption="A calm beginner-friendly visual for solving this Windows problem safely.",
        prompt=(
            "Use case: photorealistic-natural. "
            f"Create a realistic 16:9 hero image for an English beginner computer help article titled '{title}'. "
            f"Primary request: help a non-technical reader understand a safe first-step fix for {candidate.keyword}. "
            f"Scene/backdrop: {hero_subject}. "
            "Use blank cards, abstract lines, and icon-like shapes instead of any readable interface. "
            f"Composition/framing: horizontal 16:9, uncluttered desk-level editorial photo, clear foreground subject, generous negative space. "
            f"Lighting/mood: bright natural daylight, calm, reassuring, practical. Color palette: {palette}. "
            "Do not show real Microsoft logos, fake Windows UI, readable error codes, readable letters or numbers, brand marks, "
            "private information, warning screens, command prompts, registry editors, or text overlays. "
            "Avoid fake support documents, fake screenshots, scary alert dialogs, distorted hands, extra fingers, watermarks, and cartoon/vector art. "
            "Style: modern trustworthy tech-help editorial photography, polished blog image, practical and safe."
        ),
    )
    inline = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Safe step-by-step troubleshooting setup for {candidate.keyword}",
        caption="Work through the safe checks first before trying advanced repair steps.",
        prompt=(
            "Use case: photorealistic-natural. "
            f"Create a realistic 16:9 in-article image for a beginner Windows troubleshooting guide about '{candidate.keyword}'. "
            f"Primary request: visually support the step-by-step safe checks before advanced fixes. Scene/backdrop: {inline_subject}. "
            "Show a simple troubleshooting flow using abstract icons such as restart arrows, checklist, clock, shield, "
            "repair gear, Wi-Fi waves, speaker waves, folder shapes, or device outlines when relevant. Use blank cards and abstract lines only. "
            "Composition/framing: horizontal 16:9, clean in-article explanatory photo, one clear action area, no clutter. "
            f"Lighting/mood: bright, calm, beginner-friendly. Color palette: {palette}. "
            "Avoid real or fake operating-system screens, Microsoft logos, readable UI text, readable letters or numbers, "
            "error codes, scary warning overlays, command prompts, registry editors, fake official documentation, watermarks, distorted hands, and extra fingers."
        ),
    )
    return ArticleImagePlan(
        mode="codex_generated_no_api",
        strict=True,
        notes=[
            "Do not call paid image APIs in the Python pipeline.",
            "Generate these assets manually with Codex image generation, or use local SVG fallback in CI.",
            "Do not generate fake Windows UI or readable error screens.",
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
    if any(token in text for token in ["update", "0x", "error code"]):
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
        "update": "a clean home desk with a laptop displaying only abstract update, checklist, shield, and repair symbols",
        "general": "a clean home desk with a laptop, notebook, abstract checklist cards, shield, and repair symbols",
    }
    return subjects.get(scene, subjects["general"])


def _windows_inline_subject(scene: str) -> str:
    subjects = {
        "network": "a beginner-friendly desk scene showing a router, laptop, restart arrow, Wi-Fi waves, and a three-step blank checklist",
        "device": "a simple connection-check scene with a laptop, generic device outline, restart arrow, and blank troubleshooting cards",
        "audio": "a calm audio-check scene with headphones, microphone shape, volume wave icons, and blank checklist cards",
        "printer": "a home printer troubleshooting scene with cable, printer outline, clock icon, and blank step cards",
        "account": "a privacy-safe sync-check scene with cloud icons, shield icon, clock icon, and blank checklist cards",
        "files": "a file search help scene with folder cards, magnifying glass, restart arrow, and blank checklist cards",
        "recovery": "a cautious repair-prep scene with backup drive, shield, clock, and blank step cards for safe recovery order",
        "update": "an update repair flow with restart arrows, clock, shield, repair gear, and blank checklist cards",
        "general": "a simple safe troubleshooting flow with restart arrow, checklist, clock, shield, and repair gear symbols",
    }
    return subjects.get(scene, subjects["general"])


def _windows_palette(scene: str) -> str:
    palettes = {
        "network": "clean whites, soft teal accents, muted graphite, and light desk wood",
        "device": "clean whites, muted blue accents, graphite, and soft gray",
        "audio": "clean whites, soft green accents, graphite, and warm neutral desk tones",
        "printer": "clean whites, muted cyan accents, graphite, and light gray",
        "account": "clean whites, soft sky-blue accents, graphite, and gentle warm neutrals",
        "files": "clean whites, muted amber accents, graphite, and pale gray",
        "recovery": "clean whites, restrained red caution accent, graphite, and calm neutral tones",
        "update": "clean whites, soft blue accents, graphite, and light desk wood",
        "general": "clean whites, soft blue-green accents, graphite, and calm neutral tones",
    }
    return palettes.get(scene, palettes["general"])
