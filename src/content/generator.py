from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from slugify import slugify

from src.config import ROOT_DIR, Settings
from src.models import Article, ImageAsset, TopicCandidate
from src.utils.text import title_case_keyword


OFFICIAL_SOURCE_MAP = {
    "Transportation": [
        {"name": "VISITKOREA Transportation Guide", "url": "https://english.visitkorea.or.kr/"},
        {"name": "Incheon Airport Transportation", "url": "https://www.airport.kr/ap_en/index.do"},
        {"name": "Seoul Metropolitan Government", "url": "https://english.seoul.go.kr/"},
    ],
    "Mobile & Internet": [
        {"name": "VISITKOREA Travel Essentials", "url": "https://english.visitkorea.or.kr/"},
        {"name": "Incheon Airport", "url": "https://www.airport.kr/ap_en/index.do"},
    ],
    "Apps in Korea": [
        {"name": "VISITKOREA", "url": "https://english.visitkorea.or.kr/"},
        {"name": "Korea Tourism Organization", "url": "https://knto.or.kr/eng/"},
    ],
}


class EnglishArticleGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        template_dir = ROOT_DIR / "src" / "content" / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self, candidate: TopicCandidate, image: ImageAsset) -> Article:
        title_keyword = title_case_keyword(candidate.keyword)
        if candidate.intent == "how-to" or not title_keyword.lower().startswith("how"):
            title = f"How to Use {title_keyword} in Korea: Easy Guide for Foreign Visitors"
        else:
            title = f"{title_keyword}: Easy Guide for Foreign Visitors"

        title = self._normalize_title(candidate.keyword, title)
        slug = slugify(title)
        tags = self._build_tags(candidate)
        meta_description = self._meta_description(candidate.keyword)
        sources = OFFICIAL_SOURCE_MAP.get(candidate.category, OFFICIAL_SOURCE_MAP["Transportation"])

        context = {
            "title": title,
            "slug": slug,
            "category": candidate.category,
            "tags": tags,
            "meta_description": meta_description,
            "image": image,
            "intro": self._intro(candidate.keyword),
            "quick_answer": self._quick_answer(candidate.keyword),
            "basics": self._basics(candidate.keyword),
            "steps": self._steps(candidate.keyword),
            "costs_payment": self._costs_payment(candidate.keyword),
            "mistakes": self._mistakes(candidate.keyword),
            "tips": self._tips(candidate.keyword),
            "faq": self._faq(candidate.keyword),
            "sources": sources,
        }
        markdown = self.env.get_template("article.md.j2").render(**context)
        html = self.env.get_template("article.html.j2").render(**context)

        return Article(
            title=title,
            slug=slug,
            category=candidate.category,
            tags=tags,
            meta_description=meta_description,
            markdown=markdown,
            html=html,
            image=image,
            sources=sources,
            created_at=datetime.utcnow(),
        )

    def _normalize_title(self, keyword: str, default_title: str) -> str:
        normalized = keyword.lower()
        if normalized == "incheon airport to seoul":
            return "How to Get from Incheon Airport to Seoul: Easy Guide for First-Time Visitors"
        if "esim" in normalized:
            return "Korea eSIM Guide for Tourists: What to Know Before You Arrive"
        if "kakao taxi" in normalized:
            return "How to Use Kakao T Taxi in Korea as a Foreigner"
        if "ktx" in normalized:
            return "How to Buy KTX Tickets in Korea as a Foreigner"
        return default_title

    def _build_tags(self, candidate: TopicCandidate) -> list[str]:
        tags = [candidate.category, "Korea travel", "foreign visitors"]
        for word in candidate.keyword.split():
            if len(word) > 3:
                tags.append(word.lower())
        return list(dict.fromkeys(tags))[:8]

    def _meta_description(self, keyword: str) -> str:
        return f"Simple English guide to {keyword} for travelers, exchange students, and long-term foreign visitors in Korea."

    def _intro(self, keyword: str) -> str:
        return (
            f"If you are visiting Korea for the first time, {keyword} can be confusing because local apps, "
            "payment methods, signs, and transport rules may work differently from what you expect. "
            "This guide explains the practical options in clear English so you can make a confident decision."
        )

    def _quick_answer(self, keyword: str) -> list[dict[str, str]]:
        if keyword.lower() == "incheon airport to seoul":
            return [
                {"situation": "Fastest route to Seoul Station", "choice": "AREX Express Train"},
                {"situation": "Cheapest public transport", "choice": "All-Stop Airport Railroad"},
                {"situation": "Hotel is near a bus stop", "choice": "Airport Limousine Bus"},
                {"situation": "Late-night arrival or heavy luggage", "choice": "Taxi or private transfer"},
            ]
        return [
            {"situation": "First-time visitor", "choice": "Choose the simplest option with English support"},
            {"situation": "Budget traveler", "choice": "Compare public options before paying for convenience"},
            {"situation": "Long-term stay", "choice": "Set up local apps and payment methods early"},
        ]

    def _basics(self, keyword: str) -> list[str]:
        return [
            f"The most important thing is to check the latest official information before relying on any guide about {keyword}. Korea changes app features, fares, routes, and business rules regularly.",
            "Foreign visitors should also prepare a working internet connection, a saved Korean address, and a translation app before they need help in a busy station, airport, or store.",
        ]

    def _steps(self, keyword: str) -> list[str]:
        return [
            f"Decide whether {keyword} is mainly a speed, price, comfort, or convenience problem for your trip.",
            "Check your destination in Naver Map or KakaoMap instead of relying only on Google Maps.",
            "Save the Korean name and address of your destination before leaving your hotel or airport.",
            "Prepare a backup option in case your first choice is unavailable, delayed, or difficult to use.",
            "Verify prices, schedules, and operating hours on an official website before making final decisions.",
        ]

    def _mistakes(self, keyword: str) -> list[str]:
        return [
            "Assuming every Korean app accepts foreign cards or foreign phone numbers.",
            "Checking only one map app when public transportation routes are involved.",
            "Forgetting that late-night options can be limited outside central Seoul.",
            "Using outdated blog prices without checking an official source.",
        ]

    def _costs_payment(self, keyword: str) -> list[dict[str, str]]:
        return [
            {"item": "Official price or fare", "detail": "Check the latest fare on an official website or app before making a final decision."},
            {"item": "Foreign cards", "detail": "Some local apps and kiosks may reject certain foreign cards, so keep a backup card or cash."},
            {"item": "Refunds and changes", "detail": "Rules can differ by service, ticket type, provider, and purchase channel."},
            {"item": "Convenience fees", "detail": "Third-party platforms may be easier to use, but compare fees and cancellation terms."},
        ]

    def _tips(self, keyword: str) -> list[dict[str, str]]:
        return [
            {"title": "Use Korean map apps", "detail": "Naver Map and KakaoMap usually provide better local transit information."},
            {"title": "Keep your destination in Korean", "detail": "This helps taxi drivers, hotel staff, and station workers understand where you need to go."},
            {"title": "Carry a payment backup", "detail": "Some foreign cards may fail, so keeping another card or some cash can prevent stress."},
            {"title": "Check official pages", "detail": f"For {keyword}, official sources are safer than old social media posts."},
        ]

    def _faq(self, keyword: str) -> list[dict[str, str]]:
        return [
            {
                "question": f"Is {keyword} easy for foreigners?",
                "answer": "It is usually manageable, but the experience is easier if you prepare your map app, payment method, and destination information in advance.",
            },
            {
                "question": "Should I trust older blog posts?",
                "answer": "Use them for general orientation, but verify prices, routes, and rules through official websites because details can change.",
            },
            {
                "question": "Which app should I install first?",
                "answer": "For most Korea travel situations, Naver Map or KakaoMap and Papago are the most useful starting apps.",
            },
        ]
