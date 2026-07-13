from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from src.config import ROOT_DIR, load_settings
from src.content.internal_links import PublishedPost, resolve_related_posts
from src.publishing.blogger import BloggerPublisher


KST = ZoneInfo("Asia/Seoul")
TITLE_REWRITES = {
    "korea_easy_guide": {
        "How to Use Korea Working Holiday First Week Checklist in Korea: Easy Guide for Foreign Visitors": "Your First Week on a Korea Working Holiday: Setup Checklist",
        "How to Use Naver Reservation in Korea: Easy Guide for Foreign Visitors": "Naver Reservation in Korea: Account, Language, and Booking Checks",
        "How to Use Korea Convenience Store Payment Guide in Korea: Easy Guide for Foreign Visitors": "Paying at Korean Convenience Stores: Cards, Cash, T-money, and Receipts",
        "How to Use Seoul Airport Night Arrival Guide in Korea: Easy Guide for Foreign Visitors": "Landing in Seoul Late at Night: Transport and Hotel Check-In Plan",
        "How to Use Korea Duty Free Shopping Guide in Korea: Easy Guide for Foreign Visitors": "Duty-Free Shopping in Korea: Pickup, Allowances, and Refund Differences",
        "How to Use Kiosks in Korea Restaurants: Easy Guide for Foreign Visitors": "Restaurant Kiosks in Korea: Ordering, Payment, and Language Workarounds",
        "How to Book SRT Train Tickets in Korea: Easy Guide for Foreign Visitors": "SRT Tickets for Foreign Visitors: Booking, Stations, and KTX Differences",
        "How to Use a T-money Card in Korea: Easy Guide for Foreign Visitors": "T-money in Korea: Buy, Recharge, Transfer, and Refund",
        "How to Use Naver Map for Foreigners in Korea: Easy Guide for Foreign Visitors": "Naver Map in Korea: Search Addresses, Exits, and Walking Routes",
        "How to Get from Incheon Airport to Seoul: Easy Guide for First-Time Visitors": "Incheon Airport to Seoul: Choose AREX, Bus, or Taxi",
        "Olive Young Shopping in Korea for Foreigners: Easy Guide for First-Time Visitors": "Olive Young in Korea: Product Labels, Tax Refunds, and Branch Planning",
        "Where to Stay in Seoul First Time: Area Guide for Foreign Visitors": "Where to Stay in Seoul: Choose an Area by Route, Budget, and Nightlife",
        "Korean Convenience Store Food Guide for Foreign Visitors": "Korean Convenience Store Food: Labels, Heating, and Easy First Picks",
    },
    "easy_pc_fix_guide": {
        "Taskbar Not Working Windows 11: Easy Windows Fixes for Beginners": "Windows 11 Taskbar Not Working: Restart Explorer or Check the Profile?",
        "Windows Startup Apps Slowing Down Pc: Easy Windows Fixes for Beginners": "Startup Apps Slowing Down Windows: Measure Boot Impact First",
        "Printer Says Offline on Windows 11? Simple Fixes for Beginners": "Printer Offline in Windows 11: Separate a Queue Problem from a Connection Problem",
        "How to Free Up Disk Space on Windows: Safe Steps for Beginners": "Free Up Windows Disk Space Without Deleting Personal Files",
        "File Explorer Keeps Freezing on Windows: Simple Fixes for Beginners": "File Explorer Keeps Freezing: Test Quick Access, Folders, and Extensions",
        "No Sound After Windows Update? Try These Easy Steps First": "No Sound After a Windows Update: Check Output, Services, and the Driver",
        "Ethernet Connected but No Internet on Windows 11: Safe Fixes for Beginners": "Ethernet Connected but No Internet: Find the Break Between PC and Router",
        "Scanner Not Detected Windows 11: Easy Windows Fixes for Beginners": "Scanner Not Detected in Windows 11: Check the Cable, Service, and Driver Source",
        "Windows Clock Wrong Time: Easy Windows Fixes for Beginners": "Windows Clock Is Wrong: Fix Time Zone, Sync, and Dual-Boot Conflicts",
        "Mouse Cursor Disappears Windows 11: Easy Windows Fixes for Beginners": "Mouse Cursor Disappeared in Windows 11: Input, Display, and Touchpad Checks",
        "Microsoft Store Not Opening Windows 11: Easy Windows Fixes for Beginners": "Microsoft Store Won't Open: Test the Account, Cache, and App Package",
        "Keyboard Not Typing Windows 11: Easy Windows Fixes for Beginners": "Keyboard Not Typing in Windows 11: Hardware Test, Layout, and Driver Checks",
        "Photos App Not Opening Windows 11: Easy Windows Fixes for Beginners": "Photos App Won't Open in Windows 11: File Association, Repair, and Codec Checks",
        "Microsoft Store Apps Not Updating: Easy Windows Fixes for Beginners": "Microsoft Store Apps Not Updating: Queue, Account, and Licensing Checks",
        "No Internet, Secured on Windows 11: Safe Fixes for Beginners": "No Internet, Secured in Windows 11: Compare the PC, Wi-Fi, and Router",
        "Microsoft Store Download Stuck: Easy Windows Fixes for Beginners": "Microsoft Store Download Stuck: Clear the Queue Without Resetting Windows",
        "Wi-Fi Keeps Disconnecting on Windows 11: Safe Fixes for Beginners": "Wi-Fi Keeps Disconnecting in Windows 11: Find the Trigger Pattern",
        "Windows Cannot Connect to This Network: Safe Fixes for Beginners": "Windows Cannot Connect to This Network: Profile, Password, or Router?",
        "Network Adapter Missing on Windows 11: Safe Fixes for Beginners": "Network Adapter Missing in Windows 11: Device Manager and BIOS Boundaries",
        "DNS Server Not Responding on Windows 11: Safe Fixes for Beginners": "DNS Server Not Responding: Prove Whether DNS Is Actually the Cause",
        "Windows Update Cleanup Safe for Beginners: Easy Windows Fixes for Beginners": "Is Windows Update Cleanup Safe? What It Removes and What It Keeps",
        "Windows Update Download Stuck At 0: Easy Windows Fixes for Beginners": "Windows Update Stuck at 0%: Check Activity Before You Interrupt It",
        "Windows Update Error 0X80073712: What It Means and How to Fix It": "Windows Update Error 0x80073712: Repair Corrupted Update Components Safely",
        "Windows Update Pending Restart Stuck: Safe Fixes for Beginners": "Windows Update Pending Restart Won't Clear: Finish the Restart Cycle",
        "How to Check Your Windows Version: Simple Steps for Beginners": "Check Your Windows Version, Build, Edition, and System Type",
        "Wi-Fi Button Missing on Windows 11: Simple Fixes for Beginners": "Wi-Fi Button Missing in Windows 11: Airplane Mode, Adapter, and Driver Checks",
    },
}

RAW_ASSET_BASE = (
    "https://raw.githubusercontent.com/genesishjh-sketch/"
    "korea-easy-guide-automation/main/src/images/ai_assets/hosted"
)
IMAGE_REWRITES = {
    "korea_easy_guide": {
        "5362386935147860367": [
            {
                "src": f"{RAW_ASSET_BASE}/korea-taxi-without-phone-hero-20260713.jpg",
                "alt": "Hotel staff helping a foreign visitor take a taxi in Seoul without a Korean phone number",
            },
            {
                "src": f"{RAW_ASSET_BASE}/korea-taxi-without-phone-inline-20260713.jpg",
                "alt": "Hotel concierge calling a taxi and confirming the destination on a Seoul map",
            },
        ],
        "4973057393106068154": [
            {
                "src": f"{RAW_ASSET_BASE}/korea-esim-plan-activation-hero-20260713.jpg",
                "alt": "Korea eSIM, physical SIM, and pocket Wi-Fi options shown as distinct connectivity choices",
            },
            {
                "src": f"{RAW_ASSET_BASE}/korea-esim-plan-troubleshooting-inline-20260713.jpg",
                "alt": "Four-part Korea eSIM activation and connection troubleshooting flow",
            },
        ],
        "91688852272405926": [
            {
                "src": f"{RAW_ASSET_BASE}/korea-airport-limousine-bus-hero.jpg",
                "alt": "Foreign visitor planning an airport limousine bus route at Incheon Airport",
            },
            {
                "src": f"{RAW_ASSET_BASE}/korea-airport-limousine-bus-inline.jpg",
                "alt": "Airport limousine bus luggage and boarding steps for travelers in Korea",
            },
        ],
    },
    "easy_pc_fix_guide": {
        "1188431453615401172": [
            {
                "src": f"{RAW_ASSET_BASE}/pc-wifi-button-missing-hero-20260713.jpg",
                "alt": "Wi-Fi adapter hardware and radio switch components used to diagnose a missing Wi-Fi button",
            },
            {
                "src": f"{RAW_ASSET_BASE}/pc-wifi-button-missing-inline-20260713.jpg",
                "alt": "Troubleshooting path from wireless switch to adapter, router, and trusted driver package",
            },
        ],
    },
}


def run(sites: list[str] | None = None, dry_run: bool = False, images_only: bool = False) -> Path:
    selected_sites = sites or ["korea_easy_guide", "easy_pc_fix_guide"]
    stamp = datetime.now(tz=KST).strftime("%Y%m%d-%H%M%S")
    backup_dir = ROOT_DIR / "data" / "backups" / "live_posts" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    report = {"created_at_kst": datetime.now(tz=KST).isoformat(), "dry_run": dry_run, "sites": {}}

    for site in selected_sites:
        settings = load_settings(site)
        publisher = BloggerPublisher(settings)
        posts = publisher.list_live_posts(fetch_bodies=True)
        (backup_dir / f"{site}.json").write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        catalog = [
            PublishedPost(
                title=str(post.get("title") or ""),
                url=str(post.get("url") or ""),
                labels=tuple(post.get("labels") or []),
                published=str(post.get("published") or ""),
            )
            for post in posts
        ]
        site_report = {"backup": str(backup_dir / f"{site}.json"), "updated": [], "unchanged": [], "failed": []}
        for post in posts:
            post_id = str(post.get("id") or "")
            old_title = str(post.get("title") or "")
            old_html = str(post.get("content") or "")
            new_title = old_title if images_only else TITLE_REWRITES.get(site, {}).get(old_title, old_title)
            new_html = old_html
            if not images_only:
                guides = resolve_related_posts(
                    settings.site_url,
                    old_title,
                    " ".join(post.get("labels") or []),
                    current_title=old_title,
                    current_url=str(post.get("url") or ""),
                    posts=catalog,
                )
                new_html = replace_related_guides(new_html, guides)
                new_html = replace_h1(new_html, new_title)
            image_replacements = IMAGE_REWRITES.get(site, {}).get(post_id, [])
            if image_replacements:
                new_html = replace_post_images(new_html, image_replacements)
            changed = new_title != old_title or new_html != old_html
            if not changed:
                site_report["unchanged"].append({"id": post_id, "title": old_title, "url": post.get("url")})
                continue
            if dry_run:
                site_report["updated"].append(
                    {"id": post_id, "old_title": old_title, "new_title": new_title, "url": post.get("url"), "dry_run": True}
                )
                continue
            try:
                result = publisher.update_post(post_id, new_title, new_html, list(post.get("labels") or []))
                site_report["updated"].append(
                    {"id": post_id, "old_title": old_title, "new_title": new_title, "url": result.get("url") or post.get("url")}
                )
            except Exception as exc:
                site_report["failed"].append({"id": post_id, "title": old_title, "error": str(exc)})
        report["sites"][site] = site_report

    output = ROOT_DIR / "reports" / "live-post-remediation-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def replace_h1(html: str, title: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    if h1 and h1.get_text(" ", strip=True) != title:
        h1.clear()
        h1.append(title)
    return str(soup)


def replace_related_guides(html: str, guides: list[dict[str, str]]) -> str:
    if len(guides) < 3:
        return html
    soup = BeautifulSoup(html or "", "html.parser")
    article = soup.find("article") or soup
    heading = next(
        (item for item in article.find_all("h2") if item.get_text(" ", strip=True).casefold() == "related guides"),
        None,
    )
    if heading:
        cursor = heading.find_next_sibling()
        while cursor and cursor.name != "h2":
            following = cursor.find_next_sibling()
            cursor.decompose()
            cursor = following
    else:
        heading = soup.new_tag("h2")
        heading.string = "Related Guides"
        anchor = next(
            (
                item
                for item in article.find_all("h2")
                if item.get_text(" ", strip=True).casefold() in {"official links to check", "sources", "final summary"}
            ),
            None,
        )
        if anchor:
            anchor.insert_before(heading)
        else:
            article.append(heading)
    intro = soup.new_tag("p")
    intro.string = "Continue with these directly related published guides."
    listing = soup.new_tag("ul")
    for guide in guides[:3]:
        item = soup.new_tag("li")
        link = soup.new_tag("a", href=guide["url"])
        link.string = guide["title"]
        item.append(link)
        listing.append(item)
    heading.insert_after(intro)
    intro.insert_after(listing)
    return str(soup)


def replace_post_images(html: str, replacements: list[dict[str, str]]) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    images = soup.find_all("img")
    if len(images) < len(replacements):
        return html
    for image, replacement in zip(images, replacements, strict=False):
        old_src = str(image.get("src") or "")
        image["src"] = replacement["src"]
        image["alt"] = replacement["alt"]
        image["loading"] = "lazy"
        for attribute in ("srcset", "data-src", "data-original"):
            image.attrs.pop(attribute, None)
        parent_link = image.find_parent("a")
        if parent_link and str(parent_link.get("href") or "") == old_src:
            parent_link["href"] = replacement["src"]
    return str(soup)


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up and remediate live Blogger titles and direct Related Guides links.")
    parser.add_argument("--site", action="append", choices=["korea_easy_guide", "easy_pc_fix_guide"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--images-only", action="store_true")
    args = parser.parse_args()
    print(run(args.site, args.dry_run, args.images_only))


if __name__ == "__main__":
    main()
