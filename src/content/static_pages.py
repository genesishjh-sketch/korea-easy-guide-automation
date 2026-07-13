from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StaticPage:
    title: str
    slug: str
    html: str


def required_pages(site_name: str = "Korea Easy Guide", content_domain: str = "korea_travel") -> list[StaticPage]:
    if content_domain == "windows_help":
        return windows_help_pages(site_name)
    return korea_pages(site_name)


def korea_pages(site_name: str) -> list[StaticPage]:
    return [
        StaticPage(
            title="About",
            slug="about",
            html=f"""
<h1>About {site_name}</h1>
<p>{site_name} is an English-language Korea travel and living guide for foreign visitors, exchange students, working holiday visitors, and long-term residents.</p>
<p>We publish practical guides about airport transport, public transportation, SIM and eSIM setup, Korean apps, shopping, delivery services, convenience stores, accommodation, payments, and everyday life in Korea.</p>
<p>Our editorial goal is to make each guide useful before a reader arrives, while they are standing at a station, or when they need a quick backup option. We prioritize official or platform sources, clear step-by-step explanations, and realistic notes for visitors who may not speak Korean.</p>
<p>Information can change, so important details should always be checked with the linked official service, operator, or public agency before making travel decisions.</p>
""".strip(),
        ),
        StaticPage(
            title="Contact",
            slug="contact",
            html=f"""
<h1>Contact</h1>
<p>Thank you for visiting {site_name}. We welcome correction requests, topic suggestions, and feedback about unclear or outdated travel information.</p>
<p>Please include the page title, the specific sentence or section, and the official source that should be checked when sending a correction request.</p>
<p>For privacy and safety reasons, please do not send passport numbers, visa documents, payment details, financial information, medical records, or other sensitive personal information.</p>
<p>We cannot provide emergency travel, legal, medical, immigration, or one-to-one booking support. Reader feedback is reviewed to improve future guides and keep existing pages clearer.</p>
""".strip(),
        ),
        StaticPage(
            title="Privacy Policy",
            slug="privacy-policy",
            html=f"""
<h1>Privacy Policy</h1>
<p>{site_name} respects your privacy. This website may collect limited non-personal information such as browser type, device type, pages visited, referring websites, and general location data through analytics tools and advertising services.</p>
<p>This blog may use cookies, including cookies from third-party services such as Google AdSense and Google Analytics. Third-party vendors may use cookies to serve ads based on your previous visits to this and other websites.</p>
<p>You can disable cookies through your browser settings or manage ad personalization through Google's ad settings.</p>
<p>We do not sell, trade, or personally share your private information.</p>
<p>External links on this website may lead to third-party websites. We are not responsible for the privacy practices or content of those websites.</p>
<p>This Privacy Policy may be updated from time to time. The latest version will be available on this page.</p>
""".strip(),
        ),
        StaticPage(
            title="Disclaimer",
            slug="disclaimer",
            html=f"""
<h1>Disclaimer</h1>
<p>The information on {site_name} is provided for general informational purposes only. While we try to keep content accurate and updated, details such as prices, app features, transportation rules, business hours, visa-related procedures, and service availability may change without notice.</p>
<p>Readers should verify important information through official websites, service providers, or relevant authorities before making decisions.</p>
<p>{site_name} may contain affiliate links or display advertisements. If you click on certain links or ads, we may earn a small commission or advertising revenue at no additional cost to you.</p>
<p>We are not responsible for losses, inconvenience, or issues resulting from the use of information on this website.</p>
""".strip(),
        ),
        StaticPage(
            title="Terms",
            slug="terms",
            html=f"""
<h1>Terms</h1>
<p>By using {site_name}, you agree to use this website for general informational purposes only.</p>
<p>You may read, share, and link to our guides for personal travel planning or everyday Korea living reference. You may not copy, republish, scrape, or resell substantial parts of this website without permission.</p>
<p>We try to keep information useful and current, but prices, schedules, app features, store policies, transport rules, and public agency procedures may change. Always verify important details with official sources before making decisions.</p>
<p>External links are provided for reader convenience. We do not control third-party websites, apps, payment systems, or booking services.</p>
<p>These terms may be updated from time to time. Continued use of this website means you accept the latest version available on this page.</p>
""".strip(),
        ),
    ]


def windows_help_pages(site_name: str) -> list[StaticPage]:
    return [
        StaticPage(
            title="About",
            slug="about",
            html=f"""
<h1>About {site_name}</h1>
<p>{site_name} is a beginner-friendly Windows troubleshooting guide for everyday computer users.</p>
<p>We explain common Windows update, Wi-Fi, printer, Bluetooth, sound, Microsoft Store, file, search, OneDrive, account, and error-code problems in plain English.</p>
<p>Our goal is to be easier to follow than dense technical documentation while staying safer than random repair blogs. We put low-risk checks first, separate advanced fixes, and link to official Microsoft or device-maker sources whenever possible.</p>
<p>Each guide is designed to help readers understand what to try, what to avoid, what information to record, and when to stop before a repair becomes risky.</p>
""".strip(),
        ),
        StaticPage(
            title="Contact",
            slug="contact",
            html=f"""
<h1>Contact</h1>
<p>Thank you for visiting {site_name}. You can contact us with correction requests, topic suggestions, or general feedback.</p>
<p>Please include the page title, the Windows version involved, and the official Microsoft or device-maker source that should be checked when sending a correction request.</p>
<p>Please do not send passwords, license keys, BitLocker recovery keys, private documents, screenshots with personal data, financial information, or sensitive personal data.</p>
<p>We cannot provide emergency data recovery, cybersecurity incident response, or one-to-one repair support. Reader feedback is reviewed to improve future guides.</p>
""".strip(),
        ),
        StaticPage(
            title="Privacy Policy",
            slug="privacy-policy",
            html=f"""
<h1>Privacy Policy</h1>
<p>{site_name} respects your privacy. This website may collect limited non-personal information such as browser type, device type, pages visited, referring websites, and general location data through analytics and advertising services.</p>
<p>This blog may use cookies, including cookies from third-party services such as Google AdSense and Google Analytics. Third-party vendors may use cookies to serve ads based on your visits to this and other websites.</p>
<p>You can disable cookies through your browser settings or manage ad personalization through Google's ad settings.</p>
<p>We do not sell, trade, or personally share your private information.</p>
<p>External links may lead to third-party websites, including Microsoft or device-maker websites. We are not responsible for the privacy practices of those websites.</p>
<p>This Privacy Policy may be updated from time to time. The latest version will be available on this page.</p>
""".strip(),
        ),
        StaticPage(
            title="Disclaimer",
            slug="disclaimer",
            html=f"""
<h1>Disclaimer</h1>
<p>The information on {site_name} is provided for general educational purposes only. It is not professional repair, cybersecurity, legal, or data recovery advice.</p>
<p>Windows behavior, settings, update rules, and Microsoft support pages can change. Always verify important steps through official Microsoft or device-maker sources before trying advanced fixes.</p>
<p>Some troubleshooting steps can affect files, settings, drivers, or system stability. Back up important files before advanced repair, reset, recovery, partition, format, Registry, BIOS/UEFI, PowerShell, or Command Prompt steps.</p>
<p>{site_name} may contain affiliate links or display advertisements. We may earn advertising revenue at no additional cost to you.</p>
<p>We are not responsible for data loss, device damage, downtime, or other issues resulting from the use of information on this website.</p>
""".strip(),
        ),
        StaticPage(
            title="Terms",
            slug="terms",
            html=f"""
<h1>Terms</h1>
<p>By using {site_name}, you agree to use this website for general educational purposes only.</p>
<p>You may read, share, and link to our guides for personal troubleshooting reference. You may not copy, republish, scrape, or resell substantial parts of this website without permission.</p>
<p>Windows behavior, Microsoft support pages, device drivers, app versions, and manufacturer instructions can change. Always verify important steps with official Microsoft or device-maker sources before trying advanced fixes.</p>
<p>Do not use this website as a substitute for professional repair, cybersecurity, data recovery, legal, or workplace IT support. Stop and get qualified help if a device contains important data, work files, school data, or signs of hardware failure.</p>
<p>These terms may be updated from time to time. Continued use of this website means you accept the latest version available on this page.</p>
""".strip(),
        ),
    ]
