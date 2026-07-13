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
    prompt_policy: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "strict": self.strict,
            "notes": self.notes,
            "prompt_policy": self.prompt_policy,
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

    hero_concept = _korea_image_concept(candidate.keyword, title, scene, "hero")
    inline_concept = _korea_image_concept(
        candidate.keyword,
        title,
        scene,
        "inline",
        avoid_metaphor=hero_concept["metaphor"],
    )

    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} visual guide for foreign visitors in Korea",
        caption="A practical visual guide for planning this part of your Korea trip.",
        prompt=_compose_codex_image_prompt(
            domain="Korea travel guide",
            title=title,
            keyword=candidate.keyword,
            role="hero",
            reader_intent="help foreign tourists, exchange students, and long-stay visitors make a practical decision in Korea",
            concept=hero_concept,
            subject=visual_subject,
            brief=hero_brief,
            avoid=(
                "No text overlays, no readable app screens, no logos, no fake brand marks, no private information, no watermark. "
                "Avoid repeating traveler-with-phone, skyline-only, airport-luggage-only, and generic cafe-table compositions unless the article specifically needs them."
            ),
        ),
    )
    inline_checklist = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Visual checklist for {candidate.keyword} in Korea",
        caption="Use the visual checklist to avoid common mistakes before relying on the service.",
        prompt=_compose_codex_image_prompt(
            domain="Korea travel guide",
            title=title,
            keyword=candidate.keyword,
            role="inline",
            reader_intent="support the article body with a useful process, comparison, warning, or checklist visual",
            concept=inline_concept,
            subject=_inline_subject(scene),
            brief=inline_brief,
            avoid=(
                "No readable text, no Korean letters, no logos, no fake app UI, no private information, and no watermarks. "
                "Do not make this look like a second version of the hero image."
            ),
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
            "Codex app automation must generate these images with the built-in image_gen tool, copy them into article assets, copy hosted versions into src/images/ai_assets/hosted/, commit/push hosted files, then publish.",
            "Image prompts must be created as fresh article-specific art direction. Do not paste a fixed prompt formula into image_gen.",
        ],
        images=[hero, inline_checklist],
        prompt_policy=_prompt_policy("korea_travel"),
    )


def build_windows_image_plan(candidate: TopicCandidate, title: str) -> ArticleImagePlan:
    extension = "jpg"
    topic_scene = _windows_topic_scene(candidate.keyword, title)
    text = f"{candidate.keyword} {title}"
    hero_brief = _windows_visual_brief(text, topic_scene, "hero")
    inline_brief = _windows_visual_brief(text, topic_scene, "inline")
    palette = _windows_palette(topic_scene)
    hero_concept = _windows_image_concept(candidate.keyword, title, topic_scene, "hero")
    inline_concept = _windows_image_concept(
        candidate.keyword,
        title,
        topic_scene,
        "inline",
        avoid_metaphor=hero_concept["metaphor"],
    )
    hero = PlannedImage(
        role="hero",
        filename=f"ai-hero.{extension}",
        alt=f"{title} beginner-friendly Windows help visual",
        caption="A realistic beginner-friendly visual for solving this Windows problem safely.",
        prompt=_compose_codex_image_prompt(
            domain="beginner Windows help",
            title=title,
            keyword=candidate.keyword,
            role="hero",
            reader_intent="help a non-technical reader understand the problem situation before trying safe fixes",
            concept=hero_concept,
            subject=hero_brief["brief"],
            brief=hero_brief | {"palette": palette},
            avoid=(
                "Do not show real Microsoft logos, fake Windows UI, readable error codes, readable letters or numbers, brand marks, "
                "private information, warning screens, command prompts, registry editors, or text overlays. "
                "Avoid fake support documents, fake screenshots, scary alert dialogs, distorted hands, extra fingers, watermarks, "
                "generic stock-photo office scenes, and the repeated laptop-centered desk composition."
            ),
        ),
    )
    inline = PlannedImage(
        role="inline",
        filename=f"ai-inline-1.{extension}",
        alt=f"Safe step-by-step troubleshooting setup for {candidate.keyword}",
        caption="Work through the safe checks first before trying advanced repair steps.",
        prompt=_compose_codex_image_prompt(
            domain="beginner Windows help",
            title=title,
            keyword=candidate.keyword,
            role="inline",
            reader_intent="show a distinct safe process, checklist, decision flow, or cause-and-fix relationship inside the article",
            concept=inline_concept,
            subject=inline_brief["brief"],
            brief=inline_brief | {"palette": palette},
            avoid=(
                "No real or fake operating-system screens, Microsoft logos, readable UI text, error codes, scary warning overlays, "
                "command prompts, registry editors, fake official documentation, watermarks, or brand marks. "
                "Do not make this a second laptop-on-desk image."
            ),
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
            "Codex app automation must use the built-in image_gen tool for missing images; GitHub Actions alone must not try to call paid image APIs.",
            "Before calling image_gen, Codex must adapt this brief into a one-off prompt based on the article title, reader intent, recent image history, and the image role.",
        ],
        images=[hero, inline],
        prompt_policy=_prompt_policy("windows_help"),
    )


def _prompt_policy(content_domain: str) -> dict[str, str]:
    if content_domain == "windows_help":
        return {
            "generation_owner": "codex_app_automation",
            "tool": "built_in_image_gen",
            "api_cost_policy": "Do not call OpenAI Images API or external paid image APIs.",
            "prompt_method": (
                "Treat each saved prompt as an art-direction brief. Before generating, Codex must write a fresh one-off image prompt "
                "for the exact article, image role, reader intent, and recent visual history."
            ),
            "diversity_rule": (
                "Recent laptop-on-desk or generic office visuals are not acceptable unless the topic specifically requires that exact object. "
                "Hero and inline images must use different visual metaphors, camera angles, props, and composition."
            ),
            "quality_loop": (
                "If the image looks generic, repeated, off-topic, text-heavy, or too similar to recent posts, discard it and regenerate before publishing."
            ),
        }
    return {
        "generation_owner": "codex_app_automation",
        "tool": "built_in_image_gen",
        "api_cost_policy": "Do not call OpenAI Images API or external paid image APIs.",
        "prompt_method": (
            "Treat each saved prompt as an art-direction brief. Before generating, Codex must write a fresh one-off image prompt "
            "for the article, travel task, image role, and recent visual history."
        ),
        "diversity_rule": (
            "Do not repeat traveler-with-phone, luggage-at-airport, generic cafe-table, or skyline-only visuals across nearby Korea posts. "
            "Hero and inline images must have different purposes and compositions."
        ),
        "quality_loop": (
            "If the image is generic, repeated, tourist-stock-like, text-heavy, or not useful for the article, discard it and regenerate before publishing."
        ),
    }


def _compose_codex_image_prompt(
    *,
    domain: str,
    title: str,
    keyword: str,
    role: str,
    reader_intent: str,
    concept: dict[str, str],
    subject: str,
    brief: dict[str, str],
    avoid: str,
) -> str:
    palette = brief.get("palette") or f"{brief.get('accent', 'muted accent')} with clean neutrals"
    return (
        "Codex image generation brief. Fresh prompt rule: do not treat this as a reusable template; create a fresh one-off prompt before generating. "
        f"Domain: {domain}. Article title: '{title}'. Search intent / reader need: {reader_intent}. "
        f"Image role: {role}. Role purpose: {concept['purpose']}. "
        f"Visual brief: {subject}. Fresh visual metaphor: {concept['metaphor']}. Subject to visualize: {subject}. "
        f"Use case: {brief.get('use_case', concept['medium_family'])}. Medium/style: {concept['medium_family']}; {brief.get('medium', '')}. "
        f"Composition: {concept['composition']}; {brief.get('framing', '')}. "
        f"Key objects or scene cues: {concept['objects']}; {brief.get('props', '')}. "
        f"Lighting/mood: {brief.get('mood', 'calm, practical, trustworthy')}. Color palette: {palette}. "
        f"Recent-image avoidance: {concept['avoid_recent']}. "
        f"Quality bar: the result must be clearly article-specific for '{keyword}', not a generic stock image, and not a variation of the other image in this post. "
        f"Constraints: {avoid}"
    )


def _windows_image_concept(
    keyword: str,
    title: str,
    scene: str,
    role: str,
    avoid_metaphor: str | None = None,
) -> dict[str, str]:
    text = f"{keyword} {title}"
    role_purpose = {
        "hero": "show the real-world problem context or a clear visual metaphor for why the issue happens",
        "inline": "explain the safe order of checks, decision path, or cause-and-fix relationship without using screenshots",
    }
    metaphor_options = {
        "network_wifi_disconnect": [
            "an interrupted signal path as physical beads between rooms",
            "a fading bridge of light from router to device",
            "a broken route line across a home floor plan model",
        ],
        "network_cannot_connect": [
            "two device islands separated by an unfinished cable bridge",
            "a blocked path made of small matte tiles and connection dots",
            "a route map where the final connection segment is missing",
        ],
        "network_adapter_missing": [
            "a missing adapter-shaped space in a hardware tray",
            "a close inspection of ports and cable ends without any screen",
            "a tidy parts layout showing what Windows cannot see physically",
        ],
        "network_dns": [
            "a paused route through abstract server blocks",
            "a branching path where one node stops the lookup flow",
            "transparent network nodes with one amber unresolved point",
        ],
        "network": [
            "home internet as a visible route between router, room, and device",
            "connection quality as a simple physical signal path",
            "safe restart order shown as object stages",
        ],
        "printer": [
            "a paper path and cable-check story centered on the printer or scanner",
            "a close-up peripheral connection scene where the accessory is the hero",
            "a blank test page and device connection flow, not a laptop scene",
        ],
        "audio": [
            "sound waves as physical rings around headphones or microphone",
            "a quiet audio-check setup with volume represented by objects",
            "input and output paths shown as separated sound tokens",
        ],
        "device": [
            "pairing distance and connection state shown with small device tokens",
            "an accessory setup path with missing connection cue",
            "device discovery as a clean object-based inspection scene",
        ],
        "files": [
            "lost file search as a tabletop folder trail",
            "folder organization as stacked cards and a magnifier",
            "search indexing as a route through blank document tiles",
        ],
        "account": [
            "privacy-safe sync as cloud-shaped objects and shield tokens",
            "account connection as locked and unlocked blank cards",
            "sign-in flow as a calm checkpoint sequence without screens",
        ],
        "recovery": [
            "backup-first repair as drive, shield, and safe-step ladder",
            "startup recovery as a protected path with warning boundaries",
            "safe repair order as physical checkpoints",
        ],
        "update_download": [
            "paused download as a waiting path of blocks and a clock",
            "network and update progress represented by objects, not UI",
            "a stalled transfer line with safe restart cues",
        ],
        "update_cleanup": [
            "storage cleanup as sorting useful and removable blocks",
            "safe cleanup decision as containers and backup token",
            "disk space as a physical shelf being organized",
        ],
        "update_error_code": [
            "error diagnosis as a puzzle table without readable codes",
            "update failure as a calm investigation scene with magnifier and shield",
            "unknown error as a locked path through diagnostic blocks",
        ],
        "update_restart": [
            "pending restart as clock, power-cycle tokens, and waiting zone",
            "restart sequence as circular objects in a safe order",
            "patient reboot flow without screens or progress bars",
        ],
        "update": [
            "update safety as shield, repair tokens, and timeline blocks",
            "system maintenance as a neat inspection board",
            "safe update flow using abstract objects",
        ],
        "general": [
            "safe troubleshooting as a non-screen object story",
            "beginner repair order as physical checkpoints",
            "cause and next step shown as a simple visual metaphor",
        ],
    }
    medium_options = [
        "editorial object photography",
        "premium 3D educational scene",
        "macro hardware detail photo",
        "paper-and-object process visual",
        "soft isometric bitmap illustration",
        "low-key diagnostic tabletop photography",
    ]
    composition_options = [
        "no centered laptop; make the topic-specific object or metaphor the dominant subject",
        "top-down three-zone layout for problem, safe check, and next step",
        "tight macro crop with the computer only implied or secondary",
        "diagonal cause-to-fix path with clear negative space",
        "asymmetrical layout with foreground object and background context",
    ]
    object_options = {
        "hero": [
            "one topic-specific main object, one safety cue, one blank note or card",
            "physical objects that explain the issue without readable text",
            "a real accessory, cable, router, folder, clock, shield, or storage prop based on the topic",
        ],
        "inline": [
            "three distinct unlabeled checkpoints, arrows made from objects, and a safety marker",
            "blank checklist cards, cause token, safe-action token, and stop/help token",
            "a small process map built from physical props, no screenshots",
        ],
    }
    metaphors = metaphor_options.get(scene, metaphor_options["general"])
    selected_metaphor = _pick(metaphors, text, role, "metaphor")
    if avoid_metaphor and len(metaphors) > 1 and selected_metaphor == avoid_metaphor:
        selected_metaphor = _pick([metaphor for metaphor in metaphors if metaphor != avoid_metaphor], text, role, "metaphor-alt")

    return {
        "purpose": role_purpose[role],
        "metaphor": selected_metaphor,
        "medium_family": _pick(medium_options, text, role, "medium-family"),
        "composition": _pick(composition_options, text, role, "composition"),
        "objects": _pick(object_options[role], text, role, "objects"),
        "avoid_recent": (
            "avoid laptop centered on a bright desk, repeated laptop+coffee setups, generic home-office stock scenes, "
            "and using the same camera angle as the other image"
        ),
    }


def _korea_image_concept(
    keyword: str,
    title: str,
    scene: str,
    role: str,
    avoid_metaphor: str | None = None,
) -> dict[str, str]:
    text = f"{keyword} {title}"
    role_purpose = {
        "hero": "show the travel situation or decision moment the reader recognizes before taking action",
        "inline": "explain a process, comparison, mistake prevention, payment step, route choice, or preparation checklist",
    }
    metaphor_options = {
        "airport": ["arrival decision point between train, bus, and taxi", "luggage movement from gate to city route", "airport-to-city route as objects on a table"],
        "ktx": ["station-to-seat boarding flow", "ticket check and platform decision without readable text", "intercity rail timing as luggage, clock, and platform cues"],
        "esim": ["mobile connection readiness after landing", "phone setup as signal tokens and travel documents", "data access before maps and taxi use"],
        "taxi": ["safe pickup confirmation at curbside", "destination and vehicle matching without app UI", "night pickup safety with luggage and route tokens"],
        "map": ["route choice between walking, subway, and bus", "station exit orientation without readable signs", "city block route model"],
        "transport_card": ["buy, recharge, tap flow", "fare card as object sequence", "gate and convenience-store preparation"],
        "shopping": ["local service use through payment, pickup, and receipt objects", "delivery or shopping flow as household objects", "foreigner-friendly everyday errand checklist"],
        "general": ["Korea travel preparation as practical objects", "decision flow for a visitor in Korea", "mistake prevention before using a local service"],
    }
    medium_options = [
        "realistic editorial travel photography",
        "premium 3D travel-service diagram",
        "object-based flat lay with Korean travel props",
        "street-level environmental photography",
        "paper-map style bitmap illustration",
        "clean comparison-board visual made from physical objects",
    ]
    composition_options = [
        "avoid generic tourist pose; make the practical action or object dominant",
        "top-down process layout with before, during, and backup zones",
        "street-level crop focused on the action rather than skyline",
        "diagonal route or decision path with clear depth",
        "tight crop on payment, ticket, card, luggage, route, or service object",
    ]
    object_options = {
        "hero": [
            "one practical travel object, one place cue, one decision cue, no readable labels",
            "luggage/card/ticket/phone object chosen only if it fits the topic",
            "a recognizable service situation without logos or readable screens",
        ],
        "inline": [
            "three unlabeled step zones, backup option object, and mistake-prevention cue",
            "comparison tokens for option A, option B, and when to avoid each",
            "blank checklist cards, route line, payment/card object, and warning marker",
        ],
    }
    metaphors = metaphor_options.get(scene, metaphor_options["general"])
    selected_metaphor = _pick(metaphors, text, role, "korea-metaphor")
    if avoid_metaphor and len(metaphors) > 1 and selected_metaphor == avoid_metaphor:
        selected_metaphor = _pick([metaphor for metaphor in metaphors if metaphor != avoid_metaphor], text, role, "korea-metaphor-alt")

    return {
        "purpose": role_purpose[role],
        "metaphor": selected_metaphor,
        "medium_family": _pick(medium_options, text, role, "korea-medium-family"),
        "composition": _pick(composition_options, text, role, "korea-composition"),
        "objects": _pick(object_options[role], text, role, "korea-objects"),
        "avoid_recent": (
            "avoid repeated traveler holding phone, luggage-only airport shots, generic Seoul skyline, cafe-table phone setup, "
            "and using the same scene as the other image"
        ),
    }


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
