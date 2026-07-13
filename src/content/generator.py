from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from slugify import slugify

from src.config import ROOT_DIR, Settings
from src.content.internal_links import resolve_related_posts
from src.models import Article, ImageAsset, TopicCandidate
from src.utils.text import title_case_keyword


OFFICIAL_SOURCE_MAP = {
    "Transportation": [
        {"name": "VISITKOREA Transportation Guide", "url": "https://english.visitkorea.or.kr/"},
        {"name": "Incheon Airport Transportation", "url": "https://www.airport.kr/ap_en/index.do"},
        {"name": "Airport Railroad official website", "url": "https://www.airportrailroad.com/"},
        {"name": "Seoul Metropolitan Government", "url": "https://english.seoul.go.kr/"},
    ],
    "Mobile & Internet": [
        {"name": "VISITKOREA Travel Essentials", "url": "https://english.visitkorea.or.kr/"},
        {"name": "Incheon Airport", "url": "https://www.airport.kr/ap_en/index.do"},
    ],
    "Apps in Korea": [
        {"name": "VISITKOREA", "url": "https://english.visitkorea.or.kr/"},
        {"name": "Korea Tourism Organization", "url": "https://knto.or.kr/eng/"},
        {"name": "NAVER Map Google Play listing", "url": "https://play.google.com/store/apps/details?id=com.nhn.android.nmap"},
        {"name": "NAVER Map App Store listing", "url": "https://apps.apple.com/us/app/naver-maps-navigation/id311867728"},
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

    def generate(
        self,
        candidate: TopicCandidate,
        image: ImageAsset,
        inline_images: list[ImageAsset] | None = None,
    ) -> Article:
        title_keyword = title_case_keyword(candidate.keyword)
        title = self._intent_title(title_keyword, candidate)

        title = self._normalize_title(candidate.keyword, title)
        slug = slugify(title)
        tags = self._build_tags(candidate)
        meta_description = self._meta_description(candidate.keyword)
        sources = self._sources(candidate)
        inline_images = inline_images or []
        related_guides = resolve_related_posts(
            self.settings.site_url,
            candidate.keyword,
            candidate.category,
            current_title=title,
        )

        context = {
            "title": title,
            "slug": slug,
            "category": candidate.category,
            "tags": tags,
            "meta_description": meta_description,
            "image": image,
            "inline_images": inline_images,
            "intro": self._intro(candidate.keyword),
            "quick_answer": self._quick_answer(candidate.keyword),
            "basics": self._basics(candidate.keyword),
            "steps": self._steps(candidate.keyword),
            "costs_payment": self._costs_payment(candidate.keyword),
            "mistakes": self._mistakes(candidate.keyword),
            "tips": self._tips(candidate.keyword),
            "faq": self._faq(candidate.keyword),
            "related_guides": related_guides,
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
            inline_images=inline_images,
        )

    def _intent_title(self, title_keyword: str, candidate: TopicCandidate) -> str:
        normalized = title_keyword.casefold()
        if any(term in normalized for term in (" vs ", " versus ", " compare ")):
            return f"{title_keyword}: Which Option Fits Your Korea Trip?"
        if "checklist" in normalized or "before" in normalized:
            return f"{title_keyword}: A Practical Pre-Trip Checklist"
        if normalized.startswith(("where ", "best ")):
            return f"{title_keyword}: How to Choose Without Guessing"
        if normalized.startswith("how "):
            return title_keyword
        if candidate.category == "Transportation":
            return f"{title_keyword}: Routes, Fares, and Backup Options"
        if candidate.category == "Apps in Korea":
            return f"{title_keyword}: Setup, Verification, and a Backup Plan"
        if candidate.category == "Mobile & Internet":
            return f"{title_keyword}: Compatibility, Activation, and Troubleshooting"
        if candidate.category in {"Shopping", "Food & Delivery"}:
            return f"{title_keyword}: Payment, Language, and Common Mistakes"
        return f"{title_keyword}: What Foreign Visitors Need to Decide"

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
        if "t money" in normalized or "t-money" in normalized or "tmoney" in normalized:
            return "How to Use a T-money Card in Korea: Easy Guide for Foreign Visitors"
        if "olive young" in normalized:
            return "Olive Young Shopping in Korea for Foreigners: Easy Guide for First-Time Visitors"
        return default_title

    def _build_tags(self, candidate: TopicCandidate) -> list[str]:
        tags = [candidate.category, "Korea travel", "foreign visitors"]
        for word in candidate.keyword.split():
            if len(word) > 3:
                tags.append(word.lower())
        return list(dict.fromkeys(tags))[:8]

    def _meta_description(self, keyword: str) -> str:
        if self._is_tmoney(keyword):
            return "T-money card in Korea guide for visitors, covering where to buy it, how to recharge, subway and bus use, balance checks, refunds, and common mistakes."
        normalized = keyword.strip()
        if "kakao taxi" in normalized.lower():
            return "Kakao T Taxi in Korea guide for foreigners, including setup, destination search, pickup points, payment backups, and common taxi app problems."
        if "esim" in normalized.lower():
            return "Korea eSIM guide for tourists, covering when to buy, activation timing, airport setup, mobile data checks, and backup options after arrival."
        if "ktx" in normalized.lower():
            return "KTX tickets in Korea guide for foreign visitors, including booking options, station checks, seat rules, payment issues, and travel-day tips."
        if "naver map" in normalized.lower():
            return "Naver Map in Korea guide for foreign visitors, covering route search, Korean addresses, subway exits, walking directions, and common mistakes."
        return f"{normalized.title()} in Korea guide for visitors, covering practical steps, payment checks, common problems, and safe backup options."

    def _intro(self, keyword: str) -> str:
        if self._is_tmoney(keyword):
            return (
                "A T-money card is one of the easiest things to set up during your first day in Korea. "
                "It works like a rechargeable transportation card for subways, buses, and many everyday travel moments, "
                "but foreign visitors often get confused about where to buy it, how to recharge it, and when it is better than paying by single ticket. "
                "This guide explains the practical flow from airport arrival to your first subway or bus ride, with the common mistakes that usually cause delays."
            )
        return (
            f"If you are visiting Korea for the first time, {keyword} can be confusing because local apps, "
            "payment methods, signs, and transport rules may work differently from what you expect. "
            "This guide explains the practical options in clear English so you can make a confident decision."
        )

    def _quick_answer(self, keyword: str) -> list[dict[str, str]]:
        if self._is_tmoney(keyword):
            return [
                {"situation": "Most first-time visitors", "choice": "Buy a T-money card at a convenience store or station sales point"},
                {"situation": "Using subway and buses often", "choice": "Recharge the card and tap in/out instead of buying single tickets"},
                {"situation": "Arriving with no Korean cash", "choice": "Use airport transport first, then buy/recharge after finding an ATM or card-friendly store"},
                {"situation": "Staying only one or two days", "choice": "Still useful if you plan several subway or bus rides"},
                {"situation": "Want shopping or tourist benefits", "choice": "Compare T-money with Korea Tour Card, WOWPASS, or NAMANE before buying"},
            ]
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
        if self._is_tmoney(keyword):
            return [
                "T-money is a prepaid transportation card used widely in Seoul and many other parts of Korea. You add balance first, then tap the card when entering and leaving subway gates or when boarding buses.",
                "The card itself is separate from the balance. Buying a card does not mean it already has enough money for your trip, so check the stored value and recharge before you rely on it for a transfer.",
                "Foreign visitors should keep a small amount of Korean won available because some recharge machines or store counters may be easier with cash. Card payment availability can vary by location and machine.",
                "Do not treat the card as a replacement for every payment situation. It is mainly useful for transportation and selected small purchases, while hotels, restaurants, and online services usually require another payment method.",
                "For most tourists, the simplest buying path is a convenience store near your hotel, a subway station, or an airport-area transport counter if one is available. If staff do not understand the English word T-money, show 티머니 on your phone and say you want to recharge it as well.",
                "The biggest practical advantage is not only price. It is speed. You avoid buying a single-use subway ticket for every ride, and you can move between subway and bus routes with less friction when your balance is enough.",
                "If you are traveling as a family or group, each person should normally carry their own card. One card per traveler keeps fare calculation and transfers simple and avoids gate errors when several people try to pass with one card.",
                "If you plan to leave Seoul, check local compatibility before assuming the same card behavior everywhere. T-money is widely used, but local transport rules, accepted cards, and refund handling can differ by city or service.",
            ]
        return [
            f"The most important thing is to check the latest official information before relying on any guide about {keyword}. Korea changes app features, fares, routes, opening hours, and business rules regularly.",
            "Foreign visitors should prepare a working internet connection, a saved Korean address, and a translation app before they need help in a busy station, airport, shop, or hotel lobby.",
            "If your plan involves transportation, payment, tickets, shopping, delivery, or local apps, prepare a backup route or backup payment method before the day you need it.",
            "Many Korea services work smoothly once they are set up, but the first attempt can be confusing because English labels, foreign cards, passport names, and phone verification do not always behave the same way.",
            "Treat this guide as a practical checklist rather than a promise that every counter, app screen, or store policy will be identical. Staff, machine types, app versions, and local branches can vary.",
            "Before you leave your hotel, save the Korean name of the place, the address, the nearest station or landmark, and at least one official page or app link that can confirm current details.",
            "For anything time-sensitive, such as a train, airport transfer, ticket pickup, reservation, or tax refund, build in extra time. A ten-minute language or payment issue is easier to solve when you are not already late.",
            "If a foreign card fails, do not keep retrying the same method at a crowded counter. Step aside, check whether another official channel exists, and use cash, another card, or staff support when available.",
            "Visitors staying more than a few days should also separate one-time setup tasks from daily-use tasks. Installing apps, checking phone verification, saving payment backups, and learning the nearest station exit are best handled before the day becomes busy.",
            "The safest approach is to make a small first attempt before depending on the service for something important. Buy one item, test one route, check one booking screen, or confirm one counter process first, then use that successful pattern for the rest of the trip.",
            "When information conflicts, prefer the official website, official app listing, government tourism page, transport operator, or the service counter in front of you. Random screenshots and short social posts can be useful clues, but they should not be the final source for a paid decision.",
        ]

    def _steps(self, keyword: str) -> list[str]:
        if self._is_tmoney(keyword):
            return [
                "Buy a T-money card at a convenience store, subway station sales point, or other authorized location after you arrive in Korea.",
                "Recharge it immediately. Do not wait until you are standing at a subway gate with luggage. For a short Seoul stay, start with a moderate balance and add more after you understand your daily travel pattern.",
                "At a subway station, use the card reader at the gate and wait for confirmation before moving. If the gate does not open, step aside and check balance or card position instead of repeatedly tapping in a rush.",
                "Tap again when exiting the subway. This matters because the system calculates the correct fare based on your route and distance.",
                "On buses, tap when boarding. In many situations you should also tap when getting off, especially if you may transfer afterward. It is a small habit that prevents fare and transfer problems.",
                "Use Naver Map or KakaoMap to plan the route before tapping in. The card pays the fare, but it does not tell you which platform, bus stop, or exit is best.",
                "Check your remaining balance at gates, recharge machines, or some convenience stores before taking a long route late at night.",
                "Keep the card separate from other transit, hotel, and contactless bank cards when tapping. Multiple cards near the reader can cause an error or failed tap.",
                "Before your final day, decide whether to use down the balance, keep the card for a future Korea trip, or ask about refund options. Do not leave refund questions until you are already rushing to airport security.",
            ]
        return [
            f"Decide whether {keyword} is mainly a speed, price, comfort, safety, or convenience problem for your trip.",
            "Open the official website or app first, then compare it with a current map result or travel information page.",
            "Check your destination in Naver Map or KakaoMap instead of relying only on Google Maps for local routing.",
            "Save the Korean name and address of your destination before leaving your hotel, airport, station, or dorm.",
            "Confirm whether the service needs a local phone number, passport name, app account, foreign card, Korean card, or cash.",
            "Prepare a backup option in case your first choice is unavailable, delayed, fully booked, or difficult to use in English.",
            "Verify prices, schedules, refund rules, and operating hours on an official website before making final decisions.",
            "Take screenshots of key information such as route names, booking numbers, addresses, store locations, and operating hours.",
            "If staff support is needed, show one clear screen at a time: the Korean name, the address, the booking number, or the official page. Too many screenshots at once can make the conversation slower.",
            "After completing the first attempt, note what actually worked: which payment method was accepted, which app screen was useful, which station exit was closest, and whether staff asked for ID or a phone number.",
            "After using the service once, save what worked for your next trip day. Korea travel gets much easier when you reuse a verified route, app setting, or payment method.",
        ]

    def _mistakes(self, keyword: str) -> list[str]:
        if self._is_tmoney(keyword):
            return [
                "Buying the card but forgetting to add enough balance before entering the station.",
                "Keeping the card in a wallet with other contactless cards and causing reader errors.",
                "Assuming every machine or counter will accept the same foreign card payment method.",
                "Forgetting to tap out correctly, especially when transferring between subway and bus routes.",
                "Waiting until the last train or late-night bus to solve a low-balance problem.",
                "Buying a tourist-benefit card without checking whether you actually need the discounts.",
                "Treating mobile T-money information as universal. Some mobile options depend on phone type, local setup, Korean payment methods, or app availability.",
                "Assuming airport, subway station, and convenience store staff all handle refunds or balance questions in the same way.",
            ]
        return [
            "Assuming every Korean app accepts foreign cards or foreign phone numbers.",
            "Checking only one map app when public transportation routes are involved.",
            "Forgetting that late-night options can be limited outside central Seoul.",
            "Using outdated blog prices without checking an official source.",
            "Arriving without the Korean address, branch name, or station exit saved on your phone.",
            "Waiting until a staff member asks for a passport, booking number, or phone number before looking for it.",
            "Assuming airport counters, downtown branches, and online channels follow exactly the same refund or pickup rules.",
        ]

    def _costs_payment(self, keyword: str) -> list[dict[str, str]]:
        if self._is_tmoney(keyword):
            return [
                {"item": "Card purchase", "detail": "The physical card has a separate purchase cost. Designs and sales locations can vary."},
                {"item": "Recharge balance", "detail": "Add stored value before riding. Cash is often the simplest backup for recharging."},
                {"item": "Transport fares", "detail": "Subway and bus fares can change, so check official transport information for current pricing."},
                {"item": "Refunds", "detail": "Refund rules may depend on remaining balance, card type, and sales location. Ask staff before assuming it is refundable."},
                {"item": "Single-use tickets", "detail": "Single-use subway tickets can work for one ride, but they add extra steps and are less convenient for repeated travel."},
                {"item": "Tourist cards", "detail": "Korea Tour Card, WOWPASS, and NAMANE may add travel or payment features, but compare fees, reload methods, and actual benefits."},
            ]
        return [
            {"item": "Official price or fare", "detail": "Check the latest fare on an official website or app before making a final decision."},
            {"item": "Foreign cards", "detail": "Some local apps and kiosks may reject certain foreign cards, so keep a backup card or cash."},
            {"item": "Refunds and changes", "detail": "Rules can differ by service, ticket type, provider, and purchase channel."},
            {"item": "Convenience fees", "detail": "Third-party platforms may be easier to use, but compare fees and cancellation terms."},
            {"item": "Cash backup", "detail": "A small amount of Korean won is useful when machines, counters, or small branches do not handle foreign cards well."},
            {"item": "Name matching", "detail": "For bookings or refunds, use the same spelling as your passport or account whenever possible."},
        ]

    def _tips(self, keyword: str) -> list[dict[str, str]]:
        if self._is_tmoney(keyword):
            return [
                {"title": "Buy it early", "detail": "Getting the card on your first day makes subway and bus travel smoother for the rest of the trip."},
                {"title": "Keep some cash", "detail": "Cash is a practical backup when a recharge machine or counter does not accept your foreign card."},
                {"title": "Use one card per person", "detail": "Each traveler should have their own card for normal subway and bus tapping."},
                {"title": "Check the balance often", "detail": "Low balance is easier to fix before entering a station than when you are rushing for a train."},
                {"title": "Pair it with Naver Map", "detail": "Use Naver Map or KakaoMap to plan the route, then use T-money to move through the gates and buses."},
                {"title": "Write down 티머니", "detail": "Showing the Korean word helps at small counters when staff are busy or English support is limited."},
                {"title": "Do not overbuy balance", "detail": "Recharge in stages unless you already know you will use public transport heavily."},
                {"title": "Keep it after the trip", "detail": "If you expect to return to Korea, keeping the card can be easier than handling a small refund."},
            ]
        return [
            {"title": "Use Korean map apps", "detail": "Naver Map and KakaoMap usually provide better local transit information."},
            {"title": "Keep your destination in Korean", "detail": "This helps taxi drivers, hotel staff, and station workers understand where you need to go."},
            {"title": "Carry a payment backup", "detail": "Some foreign cards may fail, so keeping another card or some cash can prevent stress."},
            {"title": "Check official pages", "detail": f"For {keyword}, official sources are safer than old social media posts."},
            {"title": "Save screenshots", "detail": "Screenshots help when mobile data is slow, an app logs you out, or you need to show staff a booking detail."},
            {"title": "Avoid the last-minute attempt", "detail": "Try the app, route, ticket, or store process before the exact moment you depend on it."},
            {"title": "Compare one backup", "detail": "You do not need ten options, but you should know one safe alternative if the first plan fails."},
        ]

    def _faq(self, keyword: str) -> list[dict[str, str]]:
        if self._is_tmoney(keyword):
            return [
                {
                    "question": "Do tourists need a T-money card in Korea?",
                    "answer": "Most visitors who use subways or buses should get one. It reduces the need to buy single tickets, helps with transfers, and makes daily movement less stressful after the first setup.",
                },
                {
                    "question": "Where can I buy a T-money card?",
                    "answer": "Common places include convenience stores, subway station sales points, and transport-related counters. Availability can vary by location and card design, so ask staff if you do not see one immediately.",
                },
                {
                    "question": "Can I recharge T-money with a foreign card?",
                    "answer": "Sometimes payment options vary by machine, store, and card issuer. Keep Korean won cash or another card as a backup, especially on your first day.",
                },
                {
                    "question": "Can one T-money card be used by two people?",
                    "answer": "For normal travel, each person should use their own card. Sharing one card can cause fare and transfer problems.",
                },
                {
                    "question": "Is T-money better than a single-use subway ticket?",
                    "answer": "For repeated rides, yes. Single-use tickets are acceptable for one-off trips, but T-money is faster and easier when you use subways and buses several times.",
                },
                {
                    "question": "Should I buy T-money, Korea Tour Card, WOWPASS, or NAMANE?",
                    "answer": "Use a basic T-money card if you mainly need transportation. Compare tourist or prepaid payment cards only if you want extra shopping, cashless payment, or design features.",
                },
                {
                    "question": "Can I use T-money for taxis or convenience stores?",
                    "answer": "Some taxis and selected stores may accept it, but do not rely on it as your only payment method. Keep a regular payment card or cash backup.",
                },
            ]
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
            {
                "question": "What should I do if my foreign card does not work?",
                "answer": "Try another official channel if available, use a second card or cash, and avoid relying on only one payment method for time-sensitive plans.",
            },
            {
                "question": "Do I need Korean language skills?",
                "answer": "You do not need fluent Korean, but saving Korean names, addresses, and screenshots makes staff help much easier.",
            },
            {
                "question": "How often should I recheck information?",
                "answer": "Check once while planning and again shortly before you use the service, especially for prices, opening hours, routes, app rules, and refund conditions.",
            },
        ]

    def _is_tmoney(self, keyword: str) -> bool:
        normalized = keyword.lower()
        return "t money" in normalized or "t-money" in normalized or "tmoney" in normalized

    def _sources(self, candidate: TopicCandidate) -> list[dict[str, str]]:
        keyword = candidate.keyword.lower()
        if self._is_tmoney(candidate.keyword):
            return [
                {"name": "Tmoney official English site", "url": "https://eng.tmoney.co.kr/en/aeb/main/main/readMain.dev"},
                {"name": "VISITKOREA Transportation Cards", "url": "https://english.visitkorea.or.kr/svc/contents/contentsView.do?vcontsId=140663"},
                {"name": "Seoul Metropolitan Government official website", "url": "https://english.seoul.go.kr/"},
                {"name": "WOWPASS official website", "url": "https://www.wowpass.io/"},
                {"name": "NAMANE CARD official website", "url": "https://en.namanecard.com/"},
            ]
        if "naver map" in keyword:
            return [
                {"name": "NAVER Map Google Play listing", "url": "https://play.google.com/store/apps/details?id=com.nhn.android.nmap"},
                {"name": "NAVER Map App Store listing", "url": "https://apps.apple.com/us/app/naver-maps-navigation/id311867728"},
                {"name": "NAVER Map official BE LOCAL page", "url": "https://mkt.naver.com/belocal"},
                {"name": "KakaoMap Google Play listing", "url": "https://play.google.com/store/apps/details?id=net.daum.android.map"},
                {"name": "KakaoMap App Store listing", "url": "https://apps.apple.com/us/app/kakaomap-korea-no-1-map/id304608425"},
                {"name": "VISITKOREA official travel information", "url": "https://english.visitkorea.or.kr/"},
            ]
        if "kakao taxi" in keyword or "kakao t" in keyword:
            return [
                {"name": "Kakao T Google Play listing", "url": "https://play.google.com/store/apps/details?id=com.kakao.taxi"},
                {"name": "Kakao T App Store listing", "url": "https://apps.apple.com/us/app/kakao-t/id981110422"},
                {"name": "Kakao Mobility official website", "url": "https://www.kakaomobility.com/"},
                {"name": "Kakao T official Kakao service page", "url": "https://www.kakaocorp.com/page/service/service/KakaoT?lang=ENG"},
                {"name": "VISITKOREA official travel information", "url": "https://english.visitkorea.or.kr/"},
            ]
        if "ktx" in keyword:
            return [
                {"name": "KORAIL official website for foreigners", "url": "https://www.korail.com/global/eng/main"},
                {"name": "KORAIL ticket reservation page", "url": "https://www.korail.com/global/eng/ticket/reservation"},
                {"name": "KORAIL ticketing guide", "url": "https://www.korail.com/global/eng/passengerGuide/ticketTypes/tickets"},
                {"name": "KORAIL Pass official page", "url": "https://www.korail.com/global/eng/ticket/railpass"},
                {"name": "VISITKOREA official travel information", "url": "https://english.visitkorea.or.kr/"},
            ]
        if "incheon airport" in keyword:
            return [
                {"name": "Incheon Airport official transportation guide", "url": "https://www.airport.kr/ap_en/index.do"},
                {"name": "Airport Railroad official website", "url": "https://www.airportrailroad.com/"},
                {"name": "Airport Railroad ticket reservation page", "url": "https://www.airportrailroad.com/ticket/rsv"},
                {"name": "Seoul Metropolitan Government official website", "url": "https://english.seoul.go.kr/"},
                {"name": "VISITKOREA official travel information", "url": "https://english.visitkorea.or.kr/"},
            ]
        if "esim" in keyword:
            return [
                {"name": "SK Telecom roaming official website", "url": "https://www.skroaming.com/"},
                {"name": "KT roaming official website", "url": "https://roaming.kt.com/"},
                {"name": "LG U+ roaming official website", "url": "https://www.lguplus.com/ib-roaming"},
                {"name": "Incheon Airport official website", "url": "https://www.airport.kr/ap_en/index.do"},
                {"name": "VISITKOREA official travel information", "url": "https://english.visitkorea.or.kr/"},
            ]
        if "olive young" in keyword:
            return [
                {"name": "OLIVE YOUNG Global official website", "url": "https://global.oliveyoung.com/"},
                {"name": "OLIVE YOUNG Korea official website", "url": "https://www.oliveyoung.co.kr/"},
                {"name": "Korea Customs Service English website", "url": "https://www.customs.go.kr/english/main.do"},
                {"name": "VISITKOREA official shopping information", "url": "https://english.visitkorea.or.kr/"},
                {"name": "Seoul Metropolitan Government official website", "url": "https://english.seoul.go.kr/"},
                {"name": "NAVER Map Google Play listing", "url": "https://play.google.com/store/apps/details?id=com.nhn.android.nmap"},
                {"name": "NAVER Map App Store listing", "url": "https://apps.apple.com/us/app/naver-maps-navigation/id311867728"},
            ]
        fallback_sources = list(OFFICIAL_SOURCE_MAP.get(candidate.category, OFFICIAL_SOURCE_MAP["Transportation"]))
        fallback_sources.extend(
            [
                {"name": "Seoul Tourism official website", "url": "https://english.visitseoul.net/"},
                {"name": "Korea Customs Service English website", "url": "https://www.customs.go.kr/english/main.do"},
            ]
        )
        return fallback_sources[:6]
