from __future__ import annotations

from dataclasses import asdict, dataclass
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
    scene = detect_scene(f"{candidate.keyword} {title}")
    visual_subject = _visual_subject(scene, candidate.keyword)
    style = (
        "premium editorial travel-guide photography, realistic but clean, bright natural light, "
        "modern Korean urban environment, useful visual information, no text overlays, no logos, "
        "no distorted UI, no fake brand marks, no watermark, sharp composition, professional blog header"
    )

    hero = PlannedImage(
        role="hero",
        filename="ai-hero.jpg",
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
        filename="ai-inline-1.jpg",
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
            "Generate these assets manually with Codex image generation, then save them with the exact filenames.",
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


def _visual_subject(scene: str, keyword: str) -> str:
    subjects = {
        "airport": "a foreign traveler choosing between airport train, bus, and taxi options at Incheon Airport",
        "ktx": "a traveler preparing to board a modern KTX train at a Korean rail station",
        "esim": "a traveler setting up mobile data on a smartphone after arriving in Korea",
        "taxi": "a visitor confirming a taxi pickup point on a city street in Seoul",
        "map": "a traveler using a navigation app while walking near a Seoul subway exit",
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
        "shopping": "Check payment options and app requirements before depending on a local service.",
    }
    return captions.get(scene, "Use the visual checklist to make the process easier in Korea.")
