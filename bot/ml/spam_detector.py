"""
NeuroAntiSpam ML Spam Detector
Uses scikit-learn (free, local) + optional Google Gemini (free tier) for AI analysis.
Auto-trains on user reports and collected data.
"""

import asyncio
import json
import logging
import os
import pickle
import re
import unicodedata
from typing import Tuple, Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── Text normalizer ────────────────────────────────────────────────────────────

LEET_MAP = str.maketrans("013456789@!", "oieagsb_ga_")

def normalize_text(text: str) -> str:
    """Normalize text to defeat obfuscation tricks."""
    text = text.lower()
    text = text.translate(LEET_MAP)
    # Remove zero-width chars and other invisible Unicode
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Mn"))
    # Collapse repeated chars: heeello → hello
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    # Remove extra spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Feature extraction ─────────────────────────────────────────────────────────

URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.I)
PHONE_RE = re.compile(r"[\+7\-\(\)0-9]{10,}")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FFFF]", re.UNICODE)
CAPS_RE = re.compile(r"[A-ZА-Я]")

def extract_features_text(text: str) -> dict:
    norm = normalize_text(text)
    return {
        "length": len(text),
        "url_count": len(URL_RE.findall(text)),
        "phone_count": len(PHONE_RE.findall(text)),
        "emoji_count": len(EMOJI_RE.findall(text)),
        "caps_ratio": len(CAPS_RE.findall(text)) / max(len(text), 1),
        "exclamation_count": text.count("!"),
        "has_join_link": int(bool(re.search(r"t\.me/joinchat|t\.me/\+", text, re.I))),
        "has_earn_money": int(bool(re.search(r"зарабат|заработ|earn|money|доход|пассивн", norm))),
        "has_casino": int(bool(re.search(r"казино|casino|ставк|bet|букмекер", norm))),
        "has_crypto": int(bool(re.search(r"крипт|bitcoin|btc|usdt|binance|invest", norm))),
        "has_adult": int(bool(re.search(r"18\+|секс|porn|nude|xxx|onlyfans", norm))),
        "has_drugs": int(bool(re.search(r"наркот|drug|купить товар|закладк|меф|амфет", norm))),
        "has_promo": int(bool(re.search(r"скидк|акци|промокод|promo|discount|бесплатн", norm))),
        "has_urgency": int(bool(re.search(r"срочно|только сегодня|успей|не упусти|limited", norm))),
        "word_count": len(text.split()),
    }


# ── Keyword filter (instant, no ML needed) ────────────────────────────────────

HARD_SPAM_KEYWORDS = [
    r"t\.me/joinchat", r"t\.me/\+[A-Za-z0-9]",
    r"заработ(ок|ать) (от|до) \d+", r"пассивн\w+ доход",
    r"инвест\w+ (проект|фонд|платформ)", r"купить (закладк|товар)",
    r"казино онлайн", r"ставки на спорт",
    r"онлифанс|onlyfans\.com",
    r"наркотик|нарко|мефедрон|амфетамин",
    r"пиши в (лс|личк|дм|директ)",
    r"подпишись на канал",
    r"бесплатн\w+ крипт",
]

def keyword_score(text: str) -> Tuple[float, Optional[str]]:
    """Returns (score 0-1, matched pattern or None)."""
    norm = normalize_text(text)
    for pattern in HARD_SPAM_KEYWORDS:
        if re.search(pattern, norm, re.I):
            return 1.0, pattern
    return 0.0, None


# ── Main detector ──────────────────────────────────────────────────────────────

class SpamDetector:
    MODEL_PATH = "ml/spam_model.pkl"
    VECTORIZER_PATH = "ml/spam_vectorizer.pkl"
    GLOBAL_PHRASES_PATH = "ml/global_phrases.json"

    def __init__(self, db):
        self.db = db
        self.model = None
        self.vectorizer = None
        self.global_phrases = []
        self._gemini_key = os.getenv("GEMINI_API_KEY")

    async def load_model(self):
        """Load existing model or seed with starter data."""
        loop = asyncio.get_event_loop()
        try:
            if os.path.exists(self.MODEL_PATH) and os.path.exists(self.VECTORIZER_PATH):
                with open(self.MODEL_PATH, "rb") as f:
                    self.model = pickle.load(f)
                with open(self.VECTORIZER_PATH, "rb") as f:
                    self.vectorizer = pickle.load(f)
                logger.info("ML model loaded from disk")
            else:
                await loop.run_in_executor(None, self._seed_and_train)
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            await loop.run_in_executor(None, self._seed_and_train)

        # Load global spam phrases
        if os.path.exists(self.GLOBAL_PHRASES_PATH):
            with open(self.GLOBAL_PHRASES_PATH) as f:
                self.global_phrases = json.load(f)

    def _seed_and_train(self):
        """Train initial model on built-in seed data."""
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.pipeline import Pipeline
            import numpy as np
        except ImportError:
            logger.warning("scikit-learn not installed, ML model disabled")
            return

        spam_seeds = [
            "Зарабатывай от 50000 в месяц, пиши в лс",
            "Казино онлайн, бесплатные вращения, регистрируйся",
            "Купить закладку, быстро и анонимно",
            "Инвестиционный проект, пассивный доход 200%",
            "Подпишись на наш канал, розыгрыш айфона",
            "Крипта x10, не упусти шанс, ограниченное предложение",
            "Join our channel for free money t.me/joinchat/abc",
            "Earn $500 daily, just register now",
            "Adult content, free subscription, only today",
            "OnlyFans без подписки, всё бесплатно, пиши",
            "Ставки на спорт, прогнозы 100%, заработай",
            "Беплатная крипта, BTC раздача, только сегодня",
            "Скидка 90% только сегодня успей купить",
            "Работа из дома от 5000 в день без вложений",
            "Мефедрон амфетамин купить телеграм закладка",
        ]
        ham_seeds = [
            "Привет, как дела?",
            "Спасибо за информацию",
            "Когда будет следующая встреча?",
            "Отличная идея, поддерживаю",
            "Можете объяснить подробнее?",
            "Хороший день всем участникам группы",
            "Вопрос по теме: как настроить бота?",
            "Поздравляю с днем рождения!",
            "Согласен с предыдущим сообщением",
            "Интересная статья, спасибо что поделились",
            "Hello everyone, nice to meet you",
            "What time does the meeting start?",
            "Thanks for sharing this information",
            "Great work on the project!",
            "Could you please clarify this point?",
        ]

        texts = spam_seeds + ham_seeds
        labels = [1] * len(spam_seeds) + [0] * len(ham_seeds)

        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=50000,
            sublinear_tf=True,
        )
        X = self.vectorizer.fit_transform(texts)
        self.model = LogisticRegression(C=5.0, max_iter=1000, class_weight="balanced")
        self.model.fit(X, labels)

        os.makedirs("ml", exist_ok=True)
        with open(self.MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)
        with open(self.VECTORIZER_PATH, "wb") as f:
            pickle.dump(self.vectorizer, f)
        logger.info("ML model seeded and saved")

    async def retrain_model(self, context=None):
        """Retrain model on new reported data. Called hourly."""
        try:
            samples = await self.db.get_all_training_data()
            if len(samples) < 20:
                logger.info("Not enough training data yet, skipping retrain")
                return

            texts = [s.text for s in samples]
            labels = [int(s.is_spam) for s in samples]

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._train, texts, labels)

            await self.db.mark_samples_trained([s.id for s in samples])
            logger.info(f"Model retrained on {len(samples)} samples")
        except Exception as e:
            logger.error(f"Retrain error: {e}")

    def _train(self, texts, labels):
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            return

        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=50000,
            sublinear_tf=True,
        )
        X = self.vectorizer.fit_transform(texts)
        self.model = LogisticRegression(C=5.0, max_iter=1000, class_weight="balanced")
        self.model.fit(X, labels)

        with open(self.MODEL_PATH, "wb") as f:
            pickle.dump(self.model, f)
        with open(self.VECTORIZER_PATH, "wb") as f:
            pickle.dump(self.vectorizer, f)

    def _ml_score(self, text: str) -> float:
        """Return ML spam probability 0-1."""
        if not self.model or not self.vectorizer:
            return 0.0
        try:
            X = self.vectorizer.transform([normalize_text(text)])
            prob = self.model.predict_proba(X)[0][1]
            return float(prob)
        except Exception:
            return 0.0

    def _phrase_score(self, text: str, phrases: list) -> Tuple[float, Optional[str]]:
        norm = normalize_text(text)
        for phrase_obj in phrases:
            phrase = phrase_obj if isinstance(phrase_obj, str) else phrase_obj.phrase
            weight = 1.0 if isinstance(phrase_obj, str) else getattr(phrase_obj, "weight", 1.0)
            is_regex = False if isinstance(phrase_obj, str) else getattr(phrase_obj, "is_regex", False)
            try:
                if is_regex:
                    if re.search(phrase, norm, re.I):
                        return min(1.0, weight), phrase
                else:
                    if phrase.lower() in norm:
                        return min(1.0, weight), phrase
            except re.error:
                continue
        return 0.0, None

    async def _gemini_score(self, text: str) -> Optional[float]:
        """Call Google Gemini API (free tier) for AI analysis."""
        if not self._gemini_key or len(text) < 20:
            return None
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
        prompt = (
            "You are a spam detector for Telegram groups. "
            "Analyze the following message and respond ONLY with a JSON object: "
            '{"is_spam": true/false, "confidence": 0.0-1.0, "reason": "short reason"}. '
            "Message: " + text[:500]
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{url}?key={self._gemini_key}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw = data["candidates"][0]["content"]["parts"][0]["text"]
                        # Extract JSON
                        match = re.search(r"\{.*?\}", raw, re.S)
                        if match:
                            result = json.loads(match.group())
                            if result.get("is_spam"):
                                return float(result.get("confidence", 0.9))
                            return 0.0
        except Exception as e:
            logger.debug(f"Gemini call failed: {e}")
        return None

    async def analyze(
        self,
        text: str,
        group_phrases: list = None,
        threshold: float = 0.75,
    ) -> Tuple[bool, float, str]:
        """
        Analyze message for spam.
        Returns (is_spam, score, method).
        """
        if not text or len(text.strip()) < 5:
            return False, 0.0, "skip"

        # 1. Keyword hardcoded rules (instant)
        kw_score, matched = keyword_score(text)
        if kw_score >= 1.0:
            return True, 1.0, "keyword"

        # 2. Custom group phrases
        if group_phrases:
            ph_score, matched_phrase = self._phrase_score(text, group_phrases)
            if ph_score >= threshold:
                return True, ph_score, "phrase"

        # 3. Global phrases
        g_score, _ = self._phrase_score(text, self.global_phrases)

        # 4. ML model score
        ml_score = self._ml_score(text)

        # 5. Combine scores
        combined = max(g_score, ml_score * 0.8)

        # 6. If combined is borderline, ask Gemini
        if 0.5 <= combined < threshold and self._gemini_key:
            ai_score = await self._gemini_score(text)
            if ai_score is not None:
                combined = max(combined, ai_score)
                if combined >= threshold:
                    return True, combined, "ai"

        is_spam = combined >= threshold
        method = "ml" if ml_score > g_score else "global_phrase"
        return is_spam, combined, method

    def update_global_phrases(self, phrases: list):
        """Update phrases from GitHub shared database."""
        self.global_phrases = phrases
        os.makedirs("ml", exist_ok=True)
        with open(self.GLOBAL_PHRASES_PATH, "w") as f:
            json.dump(phrases, f, ensure_ascii=False, indent=2)
