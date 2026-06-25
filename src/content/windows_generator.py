from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import quote_plus

from jinja2 import Environment, FileSystemLoader, select_autoescape
from slugify import slugify

from src.config import ROOT_DIR, Settings
from src.models import Article, ImageAsset, TopicCandidate
from src.utils.text import title_case_keyword


MICROSOFT_SOURCES = [
    {"name": "Microsoft Support", "url": "https://support.microsoft.com/windows"},
    {"name": "Microsoft Learn Windows troubleshooting", "url": "https://learn.microsoft.com/windows/"},
    {"name": "Windows release health", "url": "https://learn.microsoft.com/windows/release-health/"},
    {"name": "Windows message center", "url": "https://learn.microsoft.com/windows/release-health/windows-message-center"},
    {"name": "Microsoft Support search: Windows troubleshooting", "url": "https://support.microsoft.com/search/results?query=Windows%20troubleshooting"},
]

TOPIC_SOURCE_RULES = [
    (
        ("text bigger", "make text bigger", "text size", "display scale", "screen resolution", "magnifier", "high contrast"),
        [
            {
                "name": "Microsoft Support: Change the size of text in Windows",
                "url": "https://support.microsoft.com/en-us/windows/change-the-size-of-text-in-windows-1d5830c3-eee3-8eaa-836b-abcc37d99b9a",
            },
            {
                "name": "Microsoft Support: Change your screen resolution and layout in Windows",
                "url": "https://support.microsoft.com/en-us/windows/change-your-screen-resolution-and-layout-in-windows-5effefe3-2eac-e306-0b5d-2073b765876b",
            },
            {
                "name": "Microsoft Support: Turn high contrast mode on or off in Windows",
                "url": "https://support.microsoft.com/en-us/windows/turn-high-contrast-mode-on-or-off-in-windows-909e9d89-a0f9-a3a9-b993-7a6dcee85025",
            },
            {
                "name": "Microsoft Support: Keyboard shortcuts in Windows",
                "url": "https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec",
            },
        ],
    ),
    (
        ("screenshot", "screen shot", "snipping tool", "print screen", "prtsc"),
        [
            {
                "name": "Microsoft Support: Use Snipping Tool to capture screenshots",
                "url": "https://support.microsoft.com/en-us/windows/use-snipping-tool-to-capture-screenshots-00246869-1843-655f-f220-97299b865f6b",
            },
            {
                "name": "Microsoft Support: Keyboard shortcut for print screen",
                "url": "https://support.microsoft.com/en-us/windows/keyboard-shortcut-for-print-screen-601210c0-b3a9-7b58-bc40-bae4dcf5f108",
            },
            {
                "name": "Microsoft Support: Keyboard shortcuts in Windows",
                "url": "https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec",
            },
            {
                "name": "Microsoft Support: Uninstall and reinstall Paint and Snipping Tool",
                "url": "https://support.microsoft.com/en-us/windows/uninstall-and-reinstall-paint-and-snipping-tool-d21261f8-1c3a-4776-9262-2d34928b1962",
            },
        ],
    ),
    (
        ("windows version", "which version", "check windows version", "32-bit", "64-bit", "system type"),
        [
            {
                "name": "Microsoft Support: Find information about your Windows device",
                "url": "https://support.microsoft.com/en-us/windows/find-information-about-your-windows-device-a66d52c8-3323-44fd-8f34-a9497bb935e1",
            },
            {
                "name": "Microsoft Support: 32-bit and 64-bit Windows FAQ",
                "url": "https://support.microsoft.com/en-us/windows/32-bit-and-64-bit-windows-frequently-asked-questions-c6ca9541-8dce-4d48-0415-94a3faa2e13d",
            },
            {
                "name": "Microsoft Support: Windows 10 support has ended",
                "url": "https://support.microsoft.com/en-us/windows/windows-10-support-has-ended-on-october-14-2025-2ca8b313-1946-43d3-b55c-2b95b107f281",
            },
            {
                "name": "Microsoft Support: How to use the PC Health Check app",
                "url": "https://support.microsoft.com/en-us/windows/how-to-use-the-pc-health-check-app-9c8abd9b-03ba-4e67-81ef-36f37caa7844",
            },
        ],
    ),
    (
        ("onedrive",),
        [
            {"name": "Microsoft Support: OneDrive help and learning", "url": "https://support.microsoft.com/onedrive"},
            {"name": "Microsoft Support search: OneDrive sync problems", "url": "https://support.microsoft.com/search/results?query=OneDrive%20sync%20problems"},
            {"name": "Microsoft Support search: OneDrive error codes", "url": "https://support.microsoft.com/search/results?query=OneDrive%20error%20code"},
        ],
    ),
    (
        ("wifi", "wi-fi", "internet", "dns", "network"),
        [
            {
                "name": "Microsoft Support: Fix Wi-Fi connection issues in Windows",
                "url": "https://support.microsoft.com/en-us/windows/fix-wi-fi-connection-issues-in-windows-9424a1f7-6a3b-65a6-4d78-7f07eee84d2c",
            },
            {
                "name": "Microsoft Support: Connect to a Wi-Fi network in Windows",
                "url": "https://support.microsoft.com/en-us/windows/connect-to-a-wi-fi-network-in-windows-1f881677-b569-0cd5-010d-e3cd3579d263",
            },
        ],
    ),
    (
        ("bluetooth", "pairing"),
        [
            {
                "name": "Microsoft Support: Fix Bluetooth problems in Windows",
                "url": "https://support.microsoft.com/en-us/windows/fix-bluetooth-problems-in-windows-723e092f-03fa-858b-5c80-131ec3fba75c",
            },
            {
                "name": "Microsoft Support: Pair a Bluetooth device in Windows",
                "url": "https://support.microsoft.com/en-us/windows/pair-a-bluetooth-device-in-windows-2be7b51f-6ae9-b757-a3b9-95ee40c3e242",
            },
            {
                "name": "Microsoft Support: Update Bluetooth drivers in Windows",
                "url": "https://support.microsoft.com/en-us/windows/update-bluetooth-drivers-in-windows-82985c06-6e99-4928-9585-900cd36d1dbc",
            },
        ],
    ),
    (
        ("printer", "scanner", "print queue"),
        [
            {
                "name": "Microsoft Support: Fix printer connection and printing problems in Windows",
                "url": "https://support.microsoft.com/en-us/windows/fix-printer-connection-and-printing-problems-in-windows-fb830bff-7702-6349-33cd-9443fe987f73",
            },
            {
                "name": "Microsoft Support: Troubleshooting offline printer problems in Windows",
                "url": "https://support.microsoft.com/en-us/windows/troubleshooting-offline-printer-problems-in-windows-9f5e98ed-0ac8-50ff-a13b-d79bf7710061",
            },
            {
                "name": "Microsoft Support: Add or install a printer in Windows",
                "url": "https://support.microsoft.com/en-us/windows/add-or-install-a-printer-in-windows-cc0724cf-793e-3542-d1ff-727e4978638b",
            },
        ],
    ),
    (
        ("usb", "camera", "touchpad", "mouse", "keyboard", "device not recognized", "device manager"),
        [
            {"name": "Microsoft Support search: device problems", "url": "https://support.microsoft.com/search/results?query=device%20not%20recognized%20Windows"},
            {"name": "Microsoft Support search: camera problems", "url": "https://support.microsoft.com/search/results?query=camera%20not%20working%20Windows"},
        ],
    ),
    (
        ("windows update", "update error", "0x"),
        [
            {
                "name": "Microsoft Support: Windows Update troubleshooter",
                "url": "https://support.microsoft.com/en-us/windows/windows-update-troubleshooter-19bc41ca-ad72-ae67-af3c-89ce169755dd",
            },
            {
                "name": "Microsoft Support: Troubleshoot problems updating Windows",
                "url": "https://support.microsoft.com/en-us/windows/troubleshoot-problems-updating-windows-188c2b0f-10a7-d72f-65b8-32d177eb136c",
            },
            {
                "name": "Microsoft Support: Install Windows updates",
                "url": "https://support.microsoft.com/en-us/windows/install-windows-updates-3c5ae7fc-9fb6-9af1-1984-b5e0412c556a",
            },
            {"name": "Windows release health known issues", "url": "https://learn.microsoft.com/windows/release-health/"},
        ],
    ),
    (
        ("microsoft store", "photos app", "calculator app", "settings app", "default apps"),
        [
            {"name": "Microsoft Support search: Microsoft Store app problems", "url": "https://support.microsoft.com/search/results?query=Microsoft%20Store%20not%20working%20Windows"},
            {"name": "Microsoft Support search: Windows apps troubleshooting", "url": "https://support.microsoft.com/search/results?query=Windows%20apps%20troubleshooting"},
        ],
    ),
    (
        ("windows search", "search not working", "indexing"),
        [
            {"name": "Microsoft Support search: Windows Search", "url": "https://support.microsoft.com/search/results?query=Windows%20Search%20not%20working"},
            {"name": "Microsoft Support search: search indexing", "url": "https://support.microsoft.com/search/results?query=Windows%20search%20indexing"},
        ],
    ),
    (
        ("file explorer", "folder", "downloads folder", "desktop icons", "recycle bin"),
        [
            {"name": "Microsoft Support search: File Explorer", "url": "https://support.microsoft.com/search/results?query=File%20Explorer%20not%20responding%20Windows"},
            {"name": "Microsoft Support search: Windows files and folders", "url": "https://support.microsoft.com/search/results?query=Windows%20files%20and%20folders"},
        ],
    ),
    (
        ("disk space", "storage space", "storage sense"),
        [
            {"name": "Microsoft Support search: free up drive space", "url": "https://support.microsoft.com/search/results?query=free%20up%20drive%20space%20Windows"},
            {"name": "Microsoft Support search: Storage Sense", "url": "https://support.microsoft.com/search/results?query=Storage%20Sense%20Windows"},
        ],
    ),
    (
        ("taskbar", "start menu", "notifications", "clock"),
        [
            {"name": "Microsoft Support search: Windows taskbar", "url": "https://support.microsoft.com/search/results?query=Windows%20taskbar%20not%20working"},
            {"name": "Microsoft Support search: Start menu", "url": "https://support.microsoft.com/search/results?query=Start%20menu%20not%20working%20Windows"},
        ],
    ),
    (
        ("safe mode", "blue screen", "automatic repair", "recovery", "bitlocker", "restore point"),
        [
            {"name": "Microsoft Support search: Windows recovery options", "url": "https://support.microsoft.com/search/results?query=Windows%20recovery%20options"},
            {"name": "Microsoft Support search: Safe Mode Windows", "url": "https://support.microsoft.com/search/results?query=start%20Windows%20in%20safe%20mode"},
        ],
    ),
]


class WindowsArticleGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        template_dir = ROOT_DIR / "src" / "content" / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        candidate: TopicCandidate,
        image: ImageAsset,
        inline_images: list[ImageAsset] | None = None,
    ) -> Article:
        topic = _topic_profile(candidate.keyword, candidate.category, self.settings.site_url)
        inline_images = inline_images or []
        context = {
            "title": topic["title"],
            "slug": topic["slug"],
            "category": candidate.category,
            "tags": self._tags(candidate),
            "meta_description": topic["meta_description"],
            "image": image,
            "inline_images": inline_images,
            "lead": topic["lead"],
            "facts": topic["facts"],
            "quick_summary": topic["quick_summary"],
            "before_start": topic["before_start"],
            "symptoms": topic["symptoms"],
            "meaning": topic["meaning"],
            "not_to_do": topic["not_to_do"],
            "try_first": topic["try_first"],
            "fixes": topic["fixes"],
            "after_each_step": topic["after_each_step"],
            "advanced_fixes": topic["advanced_fixes"],
            "stop_help": topic["stop_help"],
            "faq": topic["faq"],
            "related_guides": topic["related_guides"],
            "sources": topic["sources"],
        }
        markdown = self.env.get_template("windows_article.md.j2").render(**context)
        html = self.env.get_template("windows_article.html.j2").render(**context)
        return Article(
            title=topic["title"],
            slug=topic["slug"],
            category=candidate.category,
            tags=context["tags"],
            meta_description=topic["meta_description"],
            markdown=markdown,
            html=html,
            image=image,
            sources=topic["sources"],
            created_at=datetime.utcnow(),
            inline_images=inline_images,
        )

    def _tags(self, candidate: TopicCandidate) -> list[str]:
        tags = [candidate.category, "Windows help", "beginner PC help", "Windows 11", "Windows 10"]
        for word in candidate.keyword.replace("-", " ").split():
            if len(word) > 3:
                tags.append(word.lower())
        return list(dict.fromkeys(tags))[:10]


def _topic_profile(keyword: str, category: str, site_url: str = "") -> dict:
    normalized = keyword.lower()
    error = _error_code(normalized)
    title_keyword = title_case_keyword(keyword).replace("Wifi", "Wi-Fi")

    if error:
        title = _error_title(normalized, error)
    elif _is_wifi_disconnect_topic(normalized):
        title = "Wi-Fi Keeps Disconnecting on Windows 11: Safe Fixes for Beginners"
    elif _is_network_adapter_topic(normalized):
        title = "Network Adapter Missing on Windows 11: Safe Fixes for Beginners"
    elif _is_cannot_connect_topic(normalized):
        title = "Windows Cannot Connect to This Network: Safe Fixes for Beginners"
    elif _is_no_internet_secured_topic(normalized):
        title = "No Internet, Secured on Windows 11: Safe Fixes for Beginners"
    elif "dns" in normalized:
        title = "DNS Server Not Responding on Windows 11: Safe Fixes for Beginners"
    elif "ethernet" in normalized:
        title = "Ethernet Connected but No Internet on Windows 11: Safe Fixes for Beginners"
    elif "wifi" in normalized or "wi-fi" in normalized:
        title = "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners"
    elif "bluetooth" in normalized:
        title = "Bluetooth Not Working on Windows: Beginner-Friendly Fixes"
    elif "sound" in normalized or "audio" in normalized:
        title = "No Sound After Windows Update? Try These Easy Steps First"
    elif _is_printer_driver_unavailable_topic(normalized):
        title = "Printer Driver Unavailable on Windows 11: Safe Fixes for Beginners"
    elif _is_printer_stuck_deleting_topic(normalized):
        title = "Printer Job Stuck Deleting on Windows 11: Safe Fixes for Beginners"
    elif _is_default_printer_changing_topic(normalized):
        title = "Default Printer Keeps Changing on Windows: Safe Fixes for Beginners"
    elif _is_printer_queue_topic(normalized):
        title = "How to Clear the Printer Queue on Windows: Safe Steps for Beginners"
    elif "printer" in normalized:
        title = "Printer Says Offline on Windows 11? Simple Fixes for Beginners"
    elif "search" in normalized:
        title = "Windows Search Not Working: Beginner-Friendly Fixes to Try First"
    elif "file explorer" in normalized:
        title = "File Explorer Keeps Freezing on Windows: Simple Fixes for Beginners"
    elif "safe mode" in normalized:
        title = "How to Start Windows in Safe Mode: Beginner-Friendly Guide"
    elif "disk space" in normalized:
        title = "How to Free Up Disk Space on Windows: Safe Steps for Beginners"
    else:
        title = f"{title_keyword}: Easy Windows Fixes for Beginners"

    risk = _risk_level(normalized)
    data_loss = "Yes" if risk == "High" or any(term in normalized for term in ["disk", "recovery", "reset"]) else "No"
    estimated = "20 minutes" if risk == "High" else "10 minutes" if risk == "Medium" else "5 minutes"

    return {
        "title": title,
        "slug": slugify(title),
        "meta_description": f"Beginner-friendly Windows help for {keyword}, with safe first steps, risk level, official Microsoft sources, and clear warnings before advanced fixes.",
        "lead": (
            "This guide is written for everyday Windows users who want clear steps without risky shortcuts. "
            "Start with the low-risk checks first, stop if you see signs of data loss, and use the official Microsoft links at the end to confirm current guidance."
        ),
        "facts": {
            "applies_to": "Windows 10 / Windows 11",
            "risk_level": risk,
            "data_loss_risk": data_loss,
            "estimated_time": estimated,
            "last_checked": datetime.utcnow().strftime("%Y-%m-%d"),
        },
        "quick_summary": _quick_summary(keyword, error),
        "before_start": _before_start(normalized, error),
        "symptoms": _symptoms(normalized, error),
        "meaning": _meaning(normalized, error),
        "not_to_do": _not_to_do(normalized, risk),
        "try_first": _try_first(normalized),
        "fixes": _fixes(normalized, error),
        "after_each_step": _after_each_step(normalized),
        "advanced_fixes": _advanced_fixes(normalized, risk),
        "stop_help": [
            "Important files are missing, hidden, or cannot be opened.",
            "A drive is not detected, makes unusual noises, or asks for a BitLocker recovery key.",
            "Blue screen errors repeat after every restart.",
            "This is a work or school PC and you do not have administrator permission.",
            "A step mentions reset, recovery, partition, format, Registry, BIOS, or advanced commands and you do not understand the risk.",
        ],
        "faq": _faq(keyword, error),
        "related_guides": _related_guides(category, site_url),
        "sources": _sources_for_topic(normalized),
    }


def _error_code(text: str) -> str | None:
    match = re.search(r"0x[a-f0-9]{8}", text)
    return match.group(0).upper() if match else None


def _error_title(text: str, error: str) -> str:
    if "onedrive" in text:
        return f"OneDrive Error {error}: What It Means and How to Fix It"
    if "microsoft store" in text or "store" in text:
        return f"Microsoft Store Error {error}: What It Means and How to Fix It"
    if "windows update" in text or "update error" in text:
        return f"Windows Update Error {error}: What It Means and How to Fix It"
    return f"Windows Error {error}: What It Means and How to Fix It"


def _sources_for_topic(text: str) -> list[dict[str, str]]:
    for terms, topic_sources in TOPIC_SOURCE_RULES:
        if any(term in text for term in terms):
            return _unique_sources([*topic_sources, *MICROSOFT_SOURCES])[:8]
    sources = [*MICROSOFT_SOURCES]
    return _unique_sources(sources)[:8]


def _unique_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = []
    seen = set()
    for source in sources:
        url = source.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(source)
    return unique


def _risk_level(text: str) -> str:
    if any(term in text for term in ["reset", "format", "partition", "bios", "uefi", "registry", "recovery"]):
        return "High"
    if any(term in text for term in ["driver", "sfc", "dism", "service", "update error", "0x"]):
        return "Medium"
    return "Low"


def _is_app_topic(text: str) -> bool:
    app_terms = (
        "microsoft store",
        "photos app",
        "snipping tool",
        "calculator app",
        "settings app",
        "default apps",
    )
    return any(term in text for term in app_terms)


def _app_name(text: str) -> str:
    if "microsoft store" in text:
        return "Microsoft Store"
    if "photos app" in text:
        return "Photos app"
    if "snipping tool" in text:
        return "Snipping Tool"
    if "calculator app" in text:
        return "Calculator app"
    if "settings app" in text:
        return "Settings app"
    if "default apps" in text:
        return "Default apps"
    return "the app"


def _is_printer_queue_topic(text: str) -> bool:
    return "printer" in text and ("queue" in text or "stuck" in text or "clear" in text)


def _is_printer_driver_unavailable_topic(text: str) -> bool:
    return "printer" in text and "driver" in text and any(term in text for term in ("unavailable", "missing", "not available"))


def _is_printer_stuck_deleting_topic(text: str) -> bool:
    return "printer" in text and "deleting" in text


def _is_default_printer_changing_topic(text: str) -> bool:
    return "printer" in text and "default" in text and any(term in text for term in ("changing", "keeps", "switching", "changes"))


def _is_specific_printer_topic(text: str) -> bool:
    return any(
        predicate(text)
        for predicate in (
            _is_printer_driver_unavailable_topic,
            _is_printer_stuck_deleting_topic,
            _is_default_printer_changing_topic,
        )
    )


def _is_wifi_disconnect_topic(text: str) -> bool:
    return ("wifi" in text or "wi-fi" in text) and any(term in text for term in ("disconnect", "disconnecting", "drops", "keeps"))


def _is_network_adapter_topic(text: str) -> bool:
    return "network adapter" in text and any(term in text for term in ("missing", "disappeared", "not showing"))


def _is_cannot_connect_topic(text: str) -> bool:
    return "cannot connect to this network" in text


def _is_no_internet_secured_topic(text: str) -> bool:
    return "no internet secured" in text or "no internet, secured" in text


def _is_network_connection_topic(text: str) -> bool:
    return any(
        predicate(text)
        for predicate in (
            _is_wifi_disconnect_topic,
            _is_network_adapter_topic,
            _is_cannot_connect_topic,
            _is_no_internet_secured_topic,
        )
    ) or "dns" in text or "ethernet" in text


def _quick_summary(keyword: str, error: str | None) -> list[str]:
    normalized = keyword.lower()
    if error and "onedrive" in normalized:
        return [
            f"{error} usually points to a OneDrive sign-in or connection problem.",
            "Start with internet, date and time, Microsoft account sign-in, and OneDrive restart checks.",
            "Do not unlink, reset, or reinstall OneDrive as the first step.",
            "If OneDrive still cannot connect, use Microsoft OneDrive guidance before trying advanced repair steps.",
            "This guide keeps account and sync checks separate from advanced fixes so beginners do not risk files unnecessarily.",
            "If this is a work or school OneDrive account, check with the administrator before changing account or sync settings.",
        ]
    if error:
        return [
            f"{error} usually appears when Windows Update cannot complete normally.",
            "Start with restart, internet, free disk space, and the Windows Update troubleshooter.",
            "Do not reset the PC or edit the Registry as the first step.",
            "If updates keep failing, use Microsoft guidance before trying advanced commands.",
            "This guide keeps advanced repair steps separate so beginners do not start with risky changes.",
            "If this is a work or school device, check with the administrator before changing drivers, services, or update settings.",
        ]
    if _is_app_topic(normalized):
        app = _app_name(normalized)
        return [
            f"{app} problems are often caused by a stuck app process, a pending Microsoft Store update, or a damaged app install.",
            "Start with restart, Windows Update, Microsoft Store library updates, and the app repair option before reinstalling anything.",
            "Do not reset Windows, edit the Registry, or install third-party repair tools for a single app problem.",
            "If only one Windows app fails, focus on that app first instead of changing system-wide settings.",
            "If many built-in apps fail at once, check Windows Update and Microsoft Store updates before deeper troubleshooting.",
            "This guide keeps app repair and app reset separate so beginners understand which steps can remove app data.",
        ]
    if _is_network_connection_topic(normalized):
        focus = _network_focus(normalized)
        return [
            f"{focus} is usually caused by a connection state, adapter, driver, router, DNS, or network profile problem.",
            "Start by checking whether other devices work on the same network so you know whether the issue is the PC or the network.",
            "Do not install random driver tools or reset Windows as the first step.",
            "Use restart, adapter, router, Windows network settings, and official support steps before advanced repair.",
            "Test after each change with a simple website, not only the Windows network icon.",
            "If you need internet immediately, use a temporary trusted network, Ethernet, or phone hotspot while you troubleshoot.",
        ]
    if _is_specific_printer_topic(normalized):
        focus = _printer_focus(normalized)
        return [
            f"{focus} is usually caused by a printer setting, print queue state, driver package, or Windows printer preference.",
            "Start with the printer, cable or Wi-Fi, and Windows printer settings before removing anything.",
            "Do not install random driver tools or delete printer drivers as the first step.",
            "Use Windows Settings, Windows Update, and the printer maker's official support page for driver-related checks.",
            "Send only one short test page after each change so you do not fill the queue again.",
            "If this is a shared office or school printer, check with the person who manages it before changing default or driver settings.",
        ]
    if _is_printer_queue_topic(normalized):
        return [
            "A stuck printer queue means Windows still has one or more print jobs waiting, paused, or failing.",
            "Start by canceling stuck jobs and restarting the printer before removing devices or changing drivers.",
            "Do not repeatedly send the same document because that can fill the queue again.",
            "If the queue will not clear, restart the print spooler only after saving work and understanding that active print jobs can be removed.",
            "Use a one-page test print after each step so you know whether the queue is actually clear.",
            "If this is an office or shared printer, check whether someone else is using or managing it before deleting jobs.",
        ]
    return [
        f"The problem is usually fixable with basic Windows settings, restart, or built-in troubleshooters.",
        "Try the safest steps first before downloading tools or changing advanced settings.",
        "Stop if you see missing files, BitLocker prompts, repeated blue screens, or drive errors.",
        "Use official Microsoft or device-maker pages for drivers and repair instructions.",
        "Take notes as you go so you can undo a change or explain what happened if you need help.",
        "This guide separates simple checks from advanced fixes to reduce unnecessary risk.",
    ]


def _before_start(text: str, error: str | None) -> list[str]:
    base = [
        "Work slowly and change one thing at a time. If you try five fixes at once, it becomes hard to know which step helped or which step made the problem worse.",
        "Keep your charger connected if you are using a laptop. Troubleshooting updates, network drivers, printers, or audio devices can take longer than expected, and losing power during a repair can create a second problem.",
        "Save open documents before you begin. Most beginner steps are low risk, but restarts, troubleshooters, and driver changes can close apps or interrupt unfinished work.",
        "If this is a company, school, or shared family computer, check whether another person manages it. Some settings may be controlled by an administrator, and forcing changes can break work or school requirements.",
    ]
    if error and "onedrive" in text:
        base.extend(
            [
                "For OneDrive errors, first separate account sign-in, internet connection, and sync status. The same error can appear because the PC is offline, the Microsoft account needs attention, or OneDrive cannot reach the service.",
                "Do not delete local OneDrive folders while troubleshooting. If Files On-Demand is enabled, some files may exist online only, so deleting the wrong folder can create confusion or data loss risk.",
                "If this is a work or school OneDrive account, your organization may control sign-in, storage, or sync policies. Check with the administrator before unlinking or resetting OneDrive.",
            ]
        )
    elif error:
        base.extend(
            [
                "For Windows Update errors, do not assume the error code always has one single cause. The same code can appear because of pending restarts, network problems, free-space problems, update cache issues, or a temporary Microsoft-side issue.",
                "Before trying commands, check whether the update is known to have problems on the Windows release health page. If Microsoft is already investigating an issue, waiting may be safer than changing your PC repeatedly.",
            ]
        )
    elif _is_network_connection_topic(text):
        base.extend(
            [
                "For network connection problems, first separate the PC from the network. If other devices also fail, the router or internet service may be the real problem.",
                "If only this PC fails, write down whether the issue affects Wi-Fi, Ethernet, DNS, or one saved network profile.",
                "If you need internet immediately, use a temporary safe workaround such as Ethernet, phone hotspot, or another trusted network while you complete the checks.",
            ]
        )
    elif "wifi" in text or "wi-fi" in text:
        base.extend(
            [
                "For Wi-Fi problems, first separate the PC from the network. If phones and other laptops also cannot connect, the router or internet service may be the real problem, not Windows.",
                "If Ethernet works but Wi-Fi does not, the issue is more likely related to the wireless adapter, airplane mode, power saving, or the wireless driver.",
                "If you need internet immediately, use a temporary safe workaround such as Ethernet, phone hotspot, or another trusted network while you complete the checks.",
            ]
        )
    elif _is_specific_printer_topic(text):
        base.extend(
            [
                "For printer setting or driver problems, identify whether the problem affects only one printer, all printers, or only one document.",
                "If the printer is shared, confirm whether other people can print before changing drivers or default printer settings.",
                "Keep one short test document ready. Repeatedly printing a large file can make the queue harder to understand.",
            ]
        )
    elif _is_printer_queue_topic(text):
        base.extend(
            [
                "For printer queue problems, check whether one failed document is blocking everything behind it. A single stuck job can stop later jobs from printing.",
                "If this is a shared printer, make sure you are allowed to cancel jobs before clearing the queue.",
                "Avoid repeatedly clicking Print while troubleshooting. Each attempt can add another copy of the job to the queue.",
            ]
        )
    elif "printer" in text:
        base.extend(
            [
                "For printer problems, check the physical printer first. Paper, ink, toner, power, sleep mode, Wi-Fi status, and a stuck queue can all look like a Windows problem.",
                "If several people use the same printer, ask whether it works for someone else before removing and adding devices on your PC.",
            ]
        )
    elif _is_app_topic(text):
        app = _app_name(text)
        base.extend(
            [
                f"For {app}, first note exactly what happens: it will not open, opens and closes, freezes, saves nothing, or shows an error.",
                "Close the app before changing its settings. Repair or reset options can fail if the app is still running in the background.",
                "If you rely on the app for work or school, save any open files and check whether the same task works in another app before resetting anything.",
            ]
        )
    else:
        base.extend(
            [
                "If the problem started right after installing an app, connecting a device, or changing a setting, write that down. The timing often matters more than the exact error text.",
                "Avoid paid repair pop-ups and aggressive cleanup tools. They often make beginners feel rushed, but the safer path is to use Windows settings and official support pages first.",
            ]
        )
    return base


def _symptoms(text: str, error: str | None) -> list[str]:
    if error and "onedrive" in text:
        return [
            f"OneDrive shows {error} or says it cannot connect.",
            "OneDrive may stay signed out or ask you to sign in again.",
            "Files may stop syncing even though the PC is connected to the internet.",
            "The OneDrive cloud icon may show a warning, paused state, or connection message.",
            "Other websites may work normally while OneDrive still has trouble connecting.",
        ]
    if error:
        return [
            f"Windows Update shows {error}.",
            "The update downloads but fails during install.",
            "The PC may ask you to restart, then show the same error again.",
            "The update history may show failed install attempts.",
            "The PC may work normally except for the update problem.",
        ]
    if _is_wifi_disconnect_topic(text):
        return [
            "Wi-Fi connects, then drops again after a few minutes.",
            "The network may reconnect by itself, then disconnect again later.",
            "Other devices may stay connected while this Windows PC drops.",
            "The issue may happen after sleep mode, moving rooms, or a Windows update.",
            "A phone hotspot or Ethernet connection may work more reliably than Wi-Fi.",
        ]
    if _is_network_adapter_topic(text):
        return [
            "The network adapter is missing from Settings, Quick Settings, or Device Manager.",
            "Wi-Fi or Ethernet options may disappear after restart, sleep mode, or an update.",
            "Windows may show no available networks even though other devices can connect.",
            "The adapter may reappear after restart, then disappear again later.",
            "Internet may work only through another adapter, hotspot, or USB network device.",
        ]
    if _is_cannot_connect_topic(text):
        return [
            "Windows shows 'Cannot connect to this network'.",
            "The same Wi-Fi name may work on a phone or another computer.",
            "The saved network may fail after a password, router, or Windows update change.",
            "Windows may ask for the password again but still fail.",
            "Another network or hotspot may connect normally.",
        ]
    if _is_no_internet_secured_topic(text):
        return [
            "Windows says 'No Internet, secured' under a Wi-Fi network.",
            "The PC is connected to Wi-Fi but websites do not load.",
            "Other devices on the same network may or may not have internet.",
            "The message may appear after sleep mode, router restart, VPN use, or a Windows update.",
            "The Wi-Fi signal can look normal even though internet access is blocked.",
        ]
    if "dns" in text:
        return [
            "Windows or a browser says the DNS server is not responding.",
            "The PC may connect to Wi-Fi or Ethernet but websites do not open.",
            "Some apps may work while browser pages fail.",
            "Other devices may work normally on the same network.",
            "The issue may appear after router, VPN, DNS, or network adapter changes.",
        ]
    if "ethernet" in text:
        return [
            "The Ethernet cable shows connected, but websites do not load.",
            "Wi-Fi may work while Ethernet does not, or the opposite may happen.",
            "Windows may show an unidentified network or no internet access.",
            "The issue may start after changing router ports, cables, VPN, or adapter settings.",
            "Another cable or router port may work normally.",
        ]
    if "wifi" in text or "wi-fi" in text:
        return [
            "The Wi-Fi button is missing from Quick Settings.",
            "Only airplane mode or Bluetooth appears.",
            "The PC cannot see nearby wireless networks.",
            "Ethernet may still work, but wireless networks do not appear.",
            "The issue may start after an update, restart, sleep mode, or driver change.",
        ]
    if "bluetooth" in text:
        return [
            "Bluetooth is missing from Quick Settings or Settings.",
            "A mouse, keyboard, speaker, earbuds, or phone will not pair.",
            "The device paired before but no longer connects.",
            "Bluetooth appears to turn on, then disconnects again.",
            "The issue may start after a Windows update, restart, airplane mode change, or driver update.",
        ]
    if "sound" in text or "audio" in text:
        return ["Speakers or headphones produce no sound.", "The volume icon looks normal but nothing plays.", "The issue started after a Windows update or restart.", "Bluetooth headphones may connect but stay silent.", "One app may have sound while another app is muted."]
    if _is_printer_queue_topic(text):
        return [
            "Print jobs stay in the queue and do not finish.",
            "A document says Printing, Paused, Error, or Deleting for a long time.",
            "New print jobs line up behind an older failed job.",
            "The printer may be online, but Windows still will not send the next page.",
            "The same document may print only after canceling the stuck job or restarting the printer.",
        ]
    if _is_printer_driver_unavailable_topic(text):
        return [
            "Windows shows 'Driver is unavailable' for a printer.",
            "The printer may appear in Settings but will not print.",
            "A print job may fail even though the printer has power and paper.",
            "The problem may start after a Windows update, printer reinstall, or moving to a new PC.",
            "Another computer may print normally while this Windows PC cannot.",
        ]
    if _is_printer_stuck_deleting_topic(text):
        return [
            "A print job says Deleting for a long time.",
            "New print jobs may wait behind the stuck deleting job.",
            "The printer may not respond even after canceling the document.",
            "The queue may look empty only after restarting the printer or PC.",
            "The same document may get stuck again if you send it repeatedly.",
        ]
    if _is_default_printer_changing_topic(text):
        return [
            "Windows keeps switching the default printer.",
            "Documents open the wrong printer by default.",
            "The default printer may change after using another printer or reconnecting to a network.",
            "A shared, virtual, or PDF printer may become the default unexpectedly.",
            "The correct printer may still work when selected manually.",
        ]
    if "scanner" in text:
        return [
            "The scanner is not detected by Windows or the scanning app.",
            "The printer may print, but scanning still fails.",
            "The scanner may appear offline, unavailable, or missing from the app.",
            "The issue may start after a driver update, cable change, Wi-Fi change, or app update.",
            "Another PC or mobile app may detect the scanner while this Windows PC cannot.",
        ]
    if "printer" in text:
        return ["Windows says the printer is offline.", "Print jobs stay in the queue.", "The printer works on another device but not this PC.", "The printer appears more than once in Settings.", "A document prints only after restarting the printer or computer."]
    if _is_app_topic(text):
        app = _app_name(text)
        if "snipping tool" in text:
            return [
                "Snipping Tool does not open from Start or the keyboard shortcut.",
                "The screenshot overlay appears, then disappears or freezes.",
                "Screenshots are not saved or copied as expected.",
                "The app may show a blank window or close immediately.",
                "The problem may start after a Windows update, Microsoft Store update, or app permission change.",
            ]
        return [
            f"{app} does not open normally.",
            "The app opens and closes immediately, freezes, or shows a blank window.",
            "Only this app may fail while other Windows apps still work.",
            "The problem may start after an update, restart, sign-in change, or Store app update.",
            "Repairing the app may help before a full reset or reinstall is needed.",
        ]
    return ["The Windows feature does not respond normally.", "Restarting may help temporarily.", "The issue returns during normal use.", "The problem may affect one account, one device, or one Windows feature.", "Windows may show no clear error message."]


def _meaning(text: str, error: str | None) -> list[str]:
    if error and "onedrive" in text:
        return [
            "OneDrive may be unable to reach Microsoft services, complete sign-in, or refresh account credentials.",
            "It does not always mean your files are lost. In many cases, the PC is connected but OneDrive itself needs account, network, or sync attention.",
            "The safest approach is to confirm connection and sign-in first, then use official OneDrive support steps before resetting the app.",
        ]
    if error:
        return [
            "Windows Update may be blocked by a pending restart, low disk space, a damaged update cache, or a service problem.",
            "It does not always mean your PC is broken. Many update errors are temporary or related to a specific update package.",
            "The safest approach is to remove simple blockers first, then check whether Microsoft has listed a known issue.",
        ]
    if _is_network_connection_topic(text):
        return [
            f"{_network_focus(text)} can happen when Windows has a stale network profile, adapter state, DNS issue, router issue, or driver problem.",
            "It does not always mean the PC is broken. Often the safest fix is to reset the connection path step by step.",
            "Because network drivers affect internet access, avoid random driver installers and use official sources only.",
        ]
    if "wifi" in text or "wi-fi" in text:
        return [
            "Windows may not detect the wireless adapter, the adapter may be disabled, or the network driver may need attention.",
            "It can also happen when airplane mode, power saving, or a temporary driver state hides wireless options.",
            "Because Wi-Fi drivers affect internet access, avoid random driver installers and use official sources only.",
        ]
    if "bluetooth" in text:
        return [
            "Windows may not detect the Bluetooth adapter, the device may need pairing again, or a driver may need attention.",
            "It can also happen when airplane mode, battery saving, or a temporary hardware state disables Bluetooth.",
            "Because Bluetooth problems often involve drivers, avoid random driver tools and use Windows Update, Device Manager, or the device maker's official support page.",
        ]
    if _is_printer_queue_topic(text):
        return [
            "Windows may be waiting on a failed, paused, or corrupted print job before it can send newer jobs.",
            "This does not always mean the printer driver is broken. Often the queue just needs to be canceled and tested carefully.",
            "Start with canceling stuck jobs and restarting the printer before reinstalling anything.",
        ]
    if _is_specific_printer_topic(text):
        return [
            f"{_printer_focus(text)} usually means Windows is confused about a printer setting, queue state, or driver package.",
            "It does not always mean the printer is broken. Often the safest fix is to confirm the correct printer, clear one stuck state, then use official driver sources.",
            "Because printer driver changes can affect every print job on the PC, avoid random driver installers and make one change at a time.",
        ]
    if "printer" in text:
        return [
            "Windows may be using the wrong printer status, a stuck queue, a disconnected printer, or an outdated printer connection.",
            "A printer can also appear offline when the printer is asleep, on another Wi-Fi network, or paused in Windows.",
            "Start with connection and queue checks before removing drivers or changing advanced printer settings.",
        ]
    if _is_app_topic(text):
        app = _app_name(text)
        return [
            f"{app} may be stuck, outdated, missing a Microsoft Store update, or blocked by a damaged app package.",
            "It does not usually mean Windows itself is broken, especially if other apps still open normally.",
            "The safest path is to restart the app, update it through Microsoft Store, then use Windows app repair before trying reset or reinstall steps.",
        ]
    return [
        "This usually means Windows needs a basic reset of the affected feature, a settings check, or an official troubleshooter.",
        "Most beginner problems should be handled with reversible steps first.",
        "Advanced repair should come only after you know the simple checks did not help.",
    ]


def _not_to_do(text: str, risk: str) -> list[str]:
    values = [
        "Do not reset your PC yet.",
        "Do not download random driver tools.",
        "Do not pay for unknown repair software.",
        "Do not run commands you do not understand.",
        "Do not follow a video or forum post if it asks you to disable security features without explaining why.",
        "Do not delete system files manually.",
    ]
    if risk in {"Medium", "High"}:
        values.append("Do not edit the Registry first.")
    if risk == "High":
        values.append("Do not format your drive unless you have a backup.")
    return values


def _try_first(text: str) -> list[str]:
    base = [
        "Restart the PC once. A normal restart is different from simply closing the laptop lid.",
        "Check that Windows is connected to power and the internet.",
        "Install only updates or drivers offered through Windows Settings or the device maker.",
        "Write down what changed before the problem started, such as an update, new app, new printer, or new router.",
        "If you use antivirus, VPN, or device management software, remember that it may affect network, update, or printer behavior.",
    ]
    if _is_network_connection_topic(text):
        return [
            "Restart the PC and the router once.",
            "Check whether other devices work on the same network.",
            "Turn airplane mode off and disconnect any VPN temporarily if you normally use one.",
            "Forget and reconnect to the network only after confirming you know the Wi-Fi password.",
            *base,
        ]
    if "wifi" in text or "wi-fi" in text:
        return ["Restart the PC and router.", "Turn airplane mode off.", "Open Settings > Network & internet and check whether Wi-Fi appears.", *base]
    if "bluetooth" in text:
        return [
            "Restart the PC and the Bluetooth device.",
            "Turn airplane mode off.",
            "Open Settings > Bluetooth & devices and check whether Bluetooth appears.",
            "Keep the Bluetooth device charged and close to the PC during pairing.",
            *base,
        ]
    if _is_printer_queue_topic(text):
        return [
            "Open Settings > Bluetooth & devices > Printers & scanners and select the printer you meant to use.",
            "Open the printer queue and cancel only the stuck job first.",
            "Turn the printer off, wait about 30 seconds, turn it back on, and send one test page.",
            *base,
        ]
    if _is_specific_printer_topic(text):
        steps = [
            "Open Settings > Bluetooth & devices > Printers & scanners and select the exact printer that has the problem.",
            "Turn the printer off, wait about 30 seconds, turn it back on, and send one short test page.",
            "Check whether the same printer works from another PC or phone before changing drivers.",
            *base,
        ]
        if _is_printer_driver_unavailable_topic(text):
            steps.insert(2, "Check Windows Update and the printer maker's official support page before removing the printer.")
        if _is_printer_stuck_deleting_topic(text):
            steps.insert(2, "Wait a moment after canceling the job, because Windows can take time to remove a job marked Deleting.")
        if _is_default_printer_changing_topic(text):
            steps.insert(2, "Check which printer is currently marked Default before printing again.")
        return steps
    if "printer" in text:
        return ["Make sure the printer is turned on.", "Check the cable or Wi-Fi connection.", "Cancel stuck print jobs before adding the printer again.", *base]
    if "sound" in text or "audio" in text:
        return ["Check the volume and output device.", "Disconnect and reconnect headphones or speakers.", "Run the Windows audio troubleshooter.", *base]
    if "onedrive" in text:
        return [
            "Open a normal website to confirm the internet connection works.",
            "Check that the date, time, and time zone are correct.",
            "Open OneDrive from the taskbar cloud icon and check whether it is paused or signed out.",
            "Sign in to your Microsoft account in a browser to confirm the account itself works.",
            *base,
        ]
    if _is_app_topic(text):
        app = _app_name(text)
        return [
            f"Close {app}, open it again from Start, and check whether the problem repeats.",
            "Restart the PC once so stuck app processes are cleared.",
            "Open Microsoft Store > Library and install app updates if they are available.",
            "Open Settings > Apps > Installed apps and find the affected app before using Repair or Reset.",
            "Check that Windows is connected to the internet so Store app updates can download.",
            "Write down what changed before the problem started, such as a Windows update, Store update, new account sign-in, or permission change.",
            "If this is a work or school PC, remember that administrators may control built-in apps and Store updates.",
        ]
    return base


def _fixes(text: str, error: str | None) -> list[str]:
    if error and "onedrive" in text:
        return [
            "Select the OneDrive cloud icon in the taskbar and check whether sync is paused. Resume syncing if it is paused.",
            "Confirm your internet connection works, then try signing in to your Microsoft account in a browser.",
            "Check Windows date, time, and time zone settings because incorrect time can break sign-in.",
            "Restart OneDrive from the Start menu, then watch whether the cloud icon reconnects.",
            "Use Microsoft's OneDrive support pages for sign-in, sync, and error-code guidance before unlinking or resetting OneDrive.",
        ]
    if error:
        return [
            "Open Settings > Windows Update and select Check for updates again after one restart.",
            "Free up disk space, especially on the Windows drive, then retry the update.",
            "Run the Windows Update troubleshooter from Settings > System > Troubleshoot > Other troubleshooters.",
            "Pause updates briefly, resume them, and try again.",
            "Check Windows release health to see whether Microsoft has listed a known update issue.",
        ]
    if _is_network_connection_topic(text):
        fixes = [
            "Open Settings > Network & internet and confirm whether the affected connection is Wi-Fi or Ethernet.",
            "Restart the router and PC, then test a simple website before changing drivers.",
            "Forget the saved Wi-Fi network and reconnect if the problem is only one network and you know the password.",
            "Run the Windows network troubleshooter from Settings before using reset options.",
            "Check Device Manager for the network adapter without installing unknown driver tools.",
            "Install driver updates from Windows Update or the PC maker's official support page.",
            "Use Network reset only after basic checks, because it removes and reinstalls network adapters.",
        ]
        if "dns" in text:
            fixes.insert(2, "Restart the router and try another browser so you know whether the issue is DNS, the browser, or the whole connection.")
        if "ethernet" in text:
            fixes.insert(2, "Try another Ethernet cable or router port before changing Windows settings.")
        if _is_no_internet_secured_topic(text):
            fixes.insert(2, "Check whether the router itself has internet access. A secured Wi-Fi connection can still have no internet from the provider.")
        if _is_network_adapter_topic(text):
            fixes.insert(2, "In Device Manager, select View > Show hidden devices and look for the missing adapter before reinstalling anything.")
        return fixes
    if "wifi" in text or "wi-fi" in text:
        return [
            "Open Settings > Network & internet and confirm Wi-Fi is available.",
            "Use Network reset only after basic checks, because it removes and reinstalls network adapters.",
            "Check Device Manager for the wireless adapter without installing unknown driver tools.",
            "Install driver updates from Windows Update or the PC maker's support page.",
            "If Wi-Fi returns after a restart but disappears again, check for pending Windows updates and official driver updates.",
            "If your laptop has a physical wireless switch or keyboard shortcut, make sure it was not turned off accidentally.",
            "If other devices also cannot connect to Wi-Fi, troubleshoot the router or internet service first.",
        ]
    if "bluetooth" in text:
        return [
            "Open Settings > Bluetooth & devices and confirm Bluetooth is available.",
            "Remove the old paired device entry only if you can pair it again afterward.",
            "Run the Bluetooth troubleshooter from Windows Settings when available.",
            "Check Device Manager for the Bluetooth adapter without installing unknown driver tools.",
            "Install driver updates from Windows Update or the PC/device maker's official support page.",
            "If only one accessory fails, test that accessory with another device before changing Windows settings.",
            "If Bluetooth disappears again after sleep or restart, check for pending Windows updates and official driver updates.",
        ]
    if _is_printer_queue_topic(text):
        return [
            "Open Settings > Bluetooth & devices > Printers & scanners, choose the printer, and open the print queue.",
            "Cancel the stuck document. Wait a moment because Windows may take time to remove a job marked Deleting.",
            "Restart the printer and check for paper, ink, toner, or display messages on the printer itself.",
            "Send one short test page instead of the original large document.",
            "If the same document gets stuck again, try printing a different file so you know whether the file is the problem.",
            "If the queue still will not clear, use official Microsoft printer troubleshooting guidance before restarting print services.",
        ]
    if _is_specific_printer_topic(text):
        fixes = [
            "Open Settings > Bluetooth & devices > Printers & scanners and select the affected printer.",
            "Check the printer's own display, paper, ink or toner, cable, Wi-Fi, and power state before changing Windows.",
            "Send one short test page after each change.",
            "Use Windows Update and the printer maker's official support page for driver checks.",
            "Remove and add the printer again only after basic checks and only if you know how to reconnect it.",
            "Avoid third-party driver updater tools.",
        ]
        if _is_printer_driver_unavailable_topic(text):
            fixes.insert(1, "If Windows says the driver is unavailable, look for an official driver or app from the printer maker before deleting anything.")
        if _is_printer_stuck_deleting_topic(text):
            fixes.insert(1, "Open the print queue, cancel only the stuck deleting job, and wait before sending another document.")
            fixes.insert(3, "Restart the printer and PC once if the job remains stuck, then check the queue again.")
        if _is_default_printer_changing_topic(text):
            fixes.insert(1, "Turn off automatic default-printer switching if Windows is choosing the last-used printer instead of your preferred printer.")
            fixes.insert(2, "Manually set the correct printer as default, then test from one simple document.")
        return fixes
    if "printer" in text:
        return [
            "Open Settings > Bluetooth & devices > Printers & scanners and select the correct printer.",
            "Clear the print queue and try a one-page test print.",
            "Remove and add the printer again if the connection is stale.",
            "Use the printer maker's official support page for drivers, not unknown repair tools.",
            "Make sure Windows is not set to use the wrong copy of the same printer.",
            "If the printer is shared through another computer, confirm that computer is turned on and connected.",
        ]
    if _is_app_topic(text):
        app = _app_name(text)
        fixes = [
            f"Open {app} from the Start menu instead of a shortcut. If it opens this way, the shortcut may be the problem.",
            "Open Microsoft Store > Library and select Get updates so built-in apps can receive pending fixes.",
            f"Open Settings > Apps > Installed apps, find {app}, select Advanced options when available, and choose Repair first.",
            "If Repair does not help, use Reset only after understanding that app data or preferences may be removed.",
            "Check Windows Update because built-in app problems can be tied to pending Windows or Store components.",
            "If the app still fails, reinstall it only from Microsoft Store or official Microsoft guidance.",
        ]
        if "snipping tool" in text:
            fixes.insert(1, "Try both Start > Snipping Tool and the Windows logo key + Shift + S shortcut so you know whether the app or only the shortcut is failing.")
            fixes.append("Check whether screenshots are being copied to the clipboard, saved to the Screenshots folder, or blocked by focus/security settings.")
        return fixes
    return [
        "Open the related Windows Settings page and check the basic option first.",
        "Run the relevant Windows troubleshooter.",
        "Check for Windows updates.",
        "Restart the affected app or service only if Microsoft guidance recommends it.",
        "Try the same task in a different user account only if you understand how to switch accounts safely.",
        "Compare the issue with another device when possible so you know whether the problem is the PC, network, printer, or accessory.",
        "Keep changes small. Make one change, test it, and then continue.",
    ]


def _after_each_step(text: str) -> list[str]:
    if _is_app_topic(text):
        app = _app_name(text)
        return [
            f"After each app step, open {app} from Start and test the exact action that failed before.",
            "If a step changes app settings, write down the original setting first. This makes it easier to undo the change if it does not help.",
            "If the app works for a few minutes and then fails again, note whether it happens after restart, sleep mode, Store update, or sign-in.",
            "Do not keep repeating the same failed repair or reset step many times. If one official app repair path does not help, move on carefully or stop and ask for help.",
            "Keep screenshots of unusual messages so you can compare them with official support instructions later.",
            "If Repair helps but the issue returns after a Store update, write down the date and app version if Windows shows it.",
            "If Reset changes app preferences, set them back slowly instead of changing several options at once.",
        ]
    checks = [
        "Test the problem again before moving to the next fix. For example, check whether the Wi-Fi button returned, the printer prints one page, or Windows Update starts installing normally.",
        "If a step changes a setting, write down the original setting first. This makes it easier to undo the change if it does not help.",
        "If the problem improves for a few minutes and then returns, note the timing. A problem that returns after sleep mode, restart, or reconnecting a device can point to a driver, power, or service issue.",
        "Do not keep repeating the same failed step many times. If one official troubleshooter or setting change does not help after a reasonable try, move on carefully or stop and ask for help.",
        "Keep screenshots of unusual messages so you can compare them with official support instructions later.",
    ]
    if "wifi" in text or "wi-fi" in text:
        checks.extend(
            [
                "After each network step, try loading a simple website and checking whether other devices on the same Wi-Fi still work.",
                "If you temporarily use a phone hotspot, remember that it may use mobile data. Switch back to your normal network after testing.",
            ]
        )
    elif "bluetooth" in text:
        checks.extend(
            [
                "After each Bluetooth step, try pairing only one device at a time so the result is clear.",
                "If the device pairs but disconnects again, note whether it happens after sleep mode, restart, low battery, or moving away from the PC.",
            ]
        )
    elif "printer" in text:
        checks.extend(
            [
                "After each printer step, send only a one-page test. Avoid sending a large document repeatedly because it can fill the queue again.",
                "If the printer wakes up but still does not print, check the queue before reinstalling anything.",
            ]
        )
    else:
        checks.extend(
            [
                "After each Windows step, restart only when the setting or troubleshooter asks you to. Unnecessary restarts make the process slower and harder to track.",
                "If the same error message appears again, keep the exact wording or code for your next search or support request.",
            ]
        )
    return checks


def _network_focus(text: str) -> str:
    if _is_wifi_disconnect_topic(text):
        return "Wi-Fi that keeps disconnecting"
    if _is_network_adapter_topic(text):
        return "a missing network adapter"
    if _is_cannot_connect_topic(text):
        return "the 'Cannot connect to this network' message"
    if _is_no_internet_secured_topic(text):
        return "the 'No Internet, secured' message"
    if "dns" in text:
        return "a DNS server not responding error"
    if "ethernet" in text:
        return "Ethernet connected with no internet"
    return "a Windows network connection problem"


def _printer_focus(text: str) -> str:
    if _is_printer_driver_unavailable_topic(text):
        return "a printer driver unavailable message"
    if _is_printer_stuck_deleting_topic(text):
        return "a printer job stuck deleting"
    if _is_default_printer_changing_topic(text):
        return "a default printer that keeps changing"
    if _is_printer_queue_topic(text):
        return "a stuck printer queue"
    return "a Windows printer problem"


def _advanced_fixes(text: str, risk: str) -> list[str]:
    warning = "Warning: advanced fixes can change Windows system files or settings. Back up important files first and stop if you are not sure."
    if risk == "Low":
        return [warning, "No advanced fix is recommended as the first path for this issue. Use official Microsoft guidance if the basic steps fail."]
    return [
        warning,
        "Use SFC or DISM only from official Microsoft instructions and only if basic settings and troubleshooters fail.",
        "Uninstalling an update, resetting Windows components, or changing drivers should be done carefully and documented before you start.",
        "Registry, BIOS/UEFI, partition, reset, or format steps should be handled by an experienced person if you do not understand the risk.",
        "If you decide to use command-line repair, copy commands only from official Microsoft documentation and read what each command does first.",
        "If the PC contains important school, work, family, or business files, make a backup before any repair that changes system files or drivers.",
    ]


def _faq(keyword: str, error: str | None) -> list[dict[str, str]]:
    return [
        {"question": "Should I reset my PC first?", "answer": "No. Resetting is not a first step. Try low-risk settings, restart, troubleshooters, and official Microsoft guidance first."},
        {"question": "Is it safe to use driver updater tools?", "answer": "Avoid random driver tools. Use Windows Update, your PC maker, or the hardware maker's official website."},
        {"question": "Can this cause data loss?", "answer": "Basic checks usually do not. Advanced repair, reset, recovery, partition, or format steps can risk data loss, so back up important files first."},
        {"question": "Does this apply to both Windows 10 and Windows 11?", "answer": "Most beginner steps are similar, but menu names can differ. Check the Applies to box and official Microsoft links."},
        {"question": "When should I ask for help?", "answer": "Ask for help if files are missing, BitLocker appears, blue screens repeat, a drive is not detected, or this is a managed work or school PC."},
        {"question": "Can I skip the simple steps and try advanced repair?", "answer": "That is not recommended for beginners. Simple checks are easier to undo and often solve the problem without touching system files or drivers."},
        {"question": "Why does this guide link to Microsoft sources?", "answer": "Windows settings and update behavior can change. Official Microsoft pages are the safest place to confirm current wording, menus, and known issues."},
        {"question": "What should I write down before asking someone for help?", "answer": "Write down the error message, when it started, your Windows version, what you already tried, and whether the problem happens on another device or account. This helps support staff avoid repeating the same steps."},
        {"question": "Should I install a cleanup app to fix this faster?", "answer": "No. Cleanup and repair apps can remove useful files or change settings without explaining the risk. Use built-in Windows settings, official troubleshooters, and official vendor pages first."},
    ]


def _related_guides(category: str, site_url: str = "") -> list[dict[str, str]]:
    mapping = {
        "Windows Update": ["How to check your Windows version", "How to free up disk space on Windows", "Windows Update stuck at 100%"],
        "Wi-Fi & Internet": ["Internet connected but not working", "DNS problems on Windows", "How to reset network settings safely"],
        "Bluetooth & Devices": ["Bluetooth missing from Windows settings", "How to check Device Manager safely", "Bluetooth headphones connected but no sound"],
        "Apps & Settings": ["Microsoft Store not opening", "How to change default apps safely", "Windows Settings app not opening"],
        "Printer & Scanner": ["How to clear the printer queue", "Printer not showing in Windows", "Scanner not detected on Windows"],
    }
    titles = mapping.get(category, ["How to start Windows in Safe Mode", "How to check your Windows version", "Beginner PC troubleshooting checklist"])
    base_url = (site_url or "").rstrip("/")
    return [
        {
            "title": title,
            "url": f"{base_url}/search?q={quote_plus(title)}" if base_url else f"/search?q={quote_plus(title)}",
        }
        for title in titles
    ]
