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
<p>Welcome to {site_name}, a practical English-language guide created for travelers, exchange students, working holiday visitors, and long-term foreigners in Korea.</p>
<p>Our goal is simple: to make everyday Korea easier to understand. We publish clear guides about transportation, SIM cards and eSIMs, Korean apps, shopping, delivery services, convenience stores, accommodation, payments, and daily life tips.</p>
<p>Whether you are visiting Korea for a few days or staying for several months, {site_name} helps you save time, avoid confusion, and enjoy your stay with more confidence.</p>
""".strip(),
        ),
        StaticPage(
            title="Contact",
            slug="contact",
            html="""
<h1>Contact</h1>
<p>Thank you for visiting Korea Easy Guide. If you have questions, suggestions, correction requests, or partnership inquiries, you can contact us by email.</p>
<p>Email: contact@example.com</p>
<p>For privacy reasons, please do not send sensitive personal information such as passport numbers, financial details, visa documents, payment details, or medical records.</p>
<p>Please note that we may not be able to respond to every message, but we do our best to review all inquiries.</p>
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
    ]


def windows_help_pages(site_name: str) -> list[StaticPage]:
    return [
        StaticPage(
            title="About",
            slug="about",
            html=f"""
<h1>About {site_name}</h1>
<p>Welcome to {site_name}, a beginner-friendly Windows troubleshooting blog for everyday computer users.</p>
<p>We explain common Windows update, Wi-Fi, printer, sound, microphone, file, search, OneDrive, account, and error-code problems in plain English.</p>
<p>Our goal is to be easier than official documentation while staying safer than random repair blogs. We prioritize low-risk steps first and link to official Microsoft sources whenever possible.</p>
""".strip(),
        ),
        StaticPage(
            title="Contact",
            slug="contact",
            html=f"""
<h1>Contact</h1>
<p>Thank you for visiting {site_name}. You can contact us with correction requests, topic suggestions, or general feedback.</p>
<p>Email: contact@example.com</p>
<p>Please do not send passwords, license keys, recovery keys, private documents, financial information, or sensitive personal data.</p>
<p>We cannot provide emergency data recovery or one-to-one repair support, but we review suggestions to improve future guides.</p>
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
    ]
