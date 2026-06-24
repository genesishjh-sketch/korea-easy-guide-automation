from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StaticPage:
    title: str
    slug: str
    html: str


def required_pages(site_name: str = "Korea Easy Guide") -> list[StaticPage]:
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
