import discord
from discord.ext import commands
import json
import os
import random
import aiohttp
from datetime import datetime, timezone, timedelta

PRAYER_API = "https://api.aladhan.com/v1/timingsByCity"
PRAYER_METHOD = 4

LOCALE_CITY_MAP = {
    "ar": ("Makkah", "SA"), "ar_SA": ("Makkah", "SA"), "ar_AE": ("Dubai", "AE"),
    "ar_EG": ("Cairo", "EG"), "ar_DZ": ("Algiers", "DZ"), "ar_MA": ("Rabat", "MA"),
    "ar_TN": ("Tunis", "TN"), "ar_IQ": ("Baghdad", "IQ"), "ar_JO": ("Amman", "JO"),
    "ar_SY": ("Damascus", "SY"), "ar_SD": ("Khartoum", "SD"), "ar_LY": ("Tripoli", "LY"),
    "en_US": ("New York", "US"), "en_GB": ("London", "GB"), "en_CA": ("Toronto", "CA"),
    "en_AU": ("Sydney", "AU"), "en_IN": ("Mumbai", "IN"), "en_NG": ("Lagos", "NG"),
    "tr_TR": ("Istanbul", "TR"), "tr_CY": ("Nicosia", "CY"),
    "fr_FR": ("Paris", "FR"), "fr_BE": ("Brussels", "BE"), "fr_CH": ("Geneva", "CH"),
    "de_DE": ("Berlin", "DE"), "de_AT": ("Vienna", "AT"),
    "es_ES": ("Madrid", "ES"), "es_MX": ("Mexico City", "MX"),
    "pt_BR": ("Brasilia", "BR"), "pt_PT": ("Lisbon", "PT"),
    "ru_RU": ("Moscow", "RU"),
    "id_ID": ("Jakarta", "ID"), "ms_MY": ("Kuala Lumpur", "MY"),
    "ur_PK": ("Karachi", "PK"), "fa_IR": ("Tehran", "IR"),
    "zh_CN": ("Beijing", "CN"), "ja_JP": ("Tokyo", "JP"),
    "ko_KR": ("Seoul", "KR"), "th_TH": ("Bangkok", "TH"),
    "nl_NL": ("Rotterdam", "NL"), "sv_SE": ("Stockholm", "SE"),
    "pl_PL": ("Warsaw", "PL"), "el_GR": ("Athens", "GR"),
}

LOCALES = {
    "ar": {
        "title": "🕋 بَوَّابَةُ الأَجْرِ الإِسْلَامِيَّةُ الُموَحَّدَةُ",
        "desc": "النفحات الإيمانية والمواقيت الفورية لـ {city}",
        "prayer_title": "🕒 مواقيت الصلاة اليوم:",
        "prayer_header": "المدينة: {city} | الدولة: {country}",
        "Fajr": "🌆 الفجر", "Dhuhr": "☀️ الظهر", "Asr": "⛅ العصر",
        "Maghrib": "🌅 المغرب", "Isha": "🌌 العشاء",
        "quran_title": "📖 آية وتدبر اليوم:",
        "hadith_title": "📚 من مشكاة النبوة (حديث شريف):",
        "dhikr_title": "📿 ذكر وتذكير الساعة:",
        "tafsir": "التفسير",
        "footer": "اكتشاف تلقائي: العربية | التاريخ: {date}",
    },
    "en": {
        "title": "🕋 THE UNIFIED ISLAMIC REWARD GATEWAY",
        "desc": "Automatically detected prayer times & spiritual content for **{city}**",
        "prayer_title": "🕒 Today's Prayer Times:",
        "prayer_header": "City: {city} | Country: {country}",
        "Fajr": "🌆 Fajr", "Dhuhr": "☀️ Dhuhr", "Asr": "⛅ Asr",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isha",
        "quran_title": "📖 Verse & Reflection:",
        "hadith_title": "📚 Prophetic Hadith:",
        "dhikr_title": "📿 Remembrance:",
        "tafsir": "Tafsir",
        "footer": "Auto-detected: English | Date: {date}",
    },
    "tr": {
        "title": "🕋 BİRLEŞİK İSLAMİ ECR KAPISI",
        "desc": "**{city}** için otomatik algılanan namaz vakitleri ve manevi içerik",
        "prayer_title": "🕒 Bugünün Namaz Vakitleri:",
        "prayer_header": "Şehir: {city} | Ülke: {country}",
        "Fajr": "🌆 İmsak", "Dhuhr": "☀️ Öğle", "Asr": "⛅ İkindi",
        "Maghrib": "🌅 Akşam", "Isha": "🌌 Yatsı",
        "quran_title": "📖 Günün Ayeti ve Tefsiri:",
        "hadith_title": "📚 Hadis-i Şerif:",
        "dhikr_title": "📿 Saatin Zikri:",
        "tafsir": "Tefsir",
        "footer": "Otomatik algılama: Türkçe | Tarih: {date}",
    },
    "fr": {
        "title": "🕋 LA PORTE UNIFIÉE DE LA RÉCOMPENSE ISLAMIQUE",
        "desc": "Horaires de prière et contenu spirituel pour **{city}**",
        "prayer_title": "🕒 Horaires de Prière:",
        "prayer_header": "Ville: {city} | Pays: {country}",
        "Fajr": "🌆 Fajr", "Dhuhr": "☀️ Dhuhr", "Asr": "⛅ Asr",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isha",
        "quran_title": "📖 Verset et Réflexion:",
        "hadith_title": "📚 Hadith Prophétique:",
        "dhikr_title": "📿 Rappel de l'Heure:",
        "tafsir": "Tafsir",
        "footer": "Détection auto: Français | Date: {date}",
    },
    "de": {
        "title": "🕋 DAS VEREINIGTE ISLAMISCHE BELOHNUNGSTOR",
        "desc": "Automatisch erkannte Gebetszeiten für **{city}**",
        "prayer_title": "🕒 Heutige Gebetszeiten:",
        "prayer_header": "Stadt: {city} | Land: {country}",
        "Fajr": "🌆 Fajr", "Dhuhr": "☀️ Dhuhr", "Asr": "⛅ Asr",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isha",
        "quran_title": "📖 Vers und Betrachtung:",
        "hadith_title": "📚 Prophetischer Hadith:",
        "dhikr_title": "📿 Gedenken der Stunde:",
        "tafsir": "Tafsir",
        "footer": "Auto-erkannt: Deutsch | Datum: {date}",
    },
    "es": {
        "title": "🕋 LA PUERTA UNIFICADA DE LA RECOMPENSA ISLÁMICA",
        "desc": "Horarios de oración para **{city}** detectados automáticamente",
        "prayer_title": "🕒 Horarios de Oración:",
        "prayer_header": "Ciudad: {city} | País: {country}",
        "Fajr": "🌆 Fajr", "Dhuhr": "☀️ Dhuhr", "Asr": "⛅ Asr",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isha",
        "quran_title": "📖 Versículo y Reflexión:",
        "hadith_title": "📚 Hadiz Profético:",
        "dhikr_title": "📿 Recuerdo de la Hora:",
        "tafsir": "Tafsir",
        "footer": "Detección auto: Español | Fecha: {date}",
    },
    "pt": {
        "title": "🕋 O PORTAL UNIFICADO DA RECOMPENSA ISLÂMICA",
        "desc": "Horários de oração para **{city}** detectados automaticamente",
        "prayer_title": "🕒 Horários de Oração:",
        "prayer_header": "Cidade: {city} | País: {country}",
        "Fajr": "🌆 Fajr", "Dhuhr": "☀️ Dhuhr", "Asr": "⛅ Asr",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isha",
        "quran_title": "📖 Versículo e Reflexão:",
        "hadith_title": "📚 Hadith Profético:",
        "dhikr_title": "📿 Lembrança da Hora:",
        "tafsir": "Tafsir",
        "footer": "Detecção auto: Português | Data: {date}",
    },
    "ru": {
        "title": "🕋 ЕДИНЫЕ ВРАТА ИСЛАМСКОЙ НАГРАДЫ",
        "desc": "Автоматически определенное время намаза для **{city}**",
        "prayer_title": "🕒 Время намаза:",
        "prayer_header": "Город: {city} | Страна: {country}",
        "Fajr": "🌆 Фаджр", "Dhuhr": "☀️ Зухр", "Asr": "⛅ Аср",
        "Maghrib": "🌅 Магриб", "Isha": "🌌 Иша",
        "quran_title": "📖 Аят и толкование:",
        "hadith_title": "📚 Хадис Пророка:",
        "dhikr_title": "📿 Поминание:",
        "tafsir": "Тафсир",
        "footer": "Автоопределение: Русский | Дата: {date}",
    },
    "id": {
        "title": "🕋 PINTU PAHALA ISLAM BERSATU",
        "desc": "Waktu shalat untuk **{city}** terdeteksi otomatis",
        "prayer_title": "🕒 Waktu Shalat Hari Ini:",
        "prayer_header": "Kota: {city} | Negara: {country}",
        "Fajr": "🌆 Subuh", "Dhuhr": "☀️ Dzuhur", "Asr": "⛅ Ashar",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isya",
        "quran_title": "📖 Ayat & Renungan:",
        "hadith_title": "📚 Hadits Nabi:",
        "dhikr_title": "📿 Dzikir Saat Ini:",
        "tafsir": "Tafsir",
        "footer": "Deteksi otomatis: Indonesia | Tanggal: {date}",
    },
    "ur": {
        "title": "🕋 اسلامی اجر کا متحدہ دروازہ",
        "desc": "**{city}** کے لیے خودکار طور پر معلوم اوقات نماز",
        "prayer_title": "🕒 آج کے اوقات نماز:",
        "prayer_header": "شہر: {city} | ملک: {country}",
        "Fajr": "🌆 فجر", "Dhuhr": "☀️ ظہر", "Asr": "⛅ عصر",
        "Maghrib": "🌅 مغرب", "Isha": "🌌 عشاء",
        "quran_title": "📖 آیت و تفسیر:",
        "hadith_title": "📚 حدیث نبوی:",
        "dhikr_title": "📿 ذکر و تذکیر:",
        "tafsir": "تفسیر",
        "footer": "خودکار شناخت: اردو | تاریخ: {date}",
    },
    "fa": {
        "title": "🕋 دروازه یکپارچه پاداش اسلامی",
        "desc": "اوقات شرعی برای **{city}** به صورت خودکار تشخیص داده شد",
        "prayer_title": "🕒 اوقات شرعی امروز:",
        "prayer_header": "شهر: {city} | کشور: {country}",
        "Fajr": "🌆 صبح", "Dhuhr": "☀️ ظهر", "Asr": "⛅ عصر",
        "Maghrib": "🌅 مغرب", "Isha": "🌌 عشا",
        "quran_title": "📖 آیه و تدبر:",
        "hadith_title": "📚 حدیث نبوی:",
        "dhikr_title": "📿 ذکر ساعت:",
        "tafsir": "تفسیر",
        "footer": "تشخیص خودکار: فارسی | تاریخ: {date}",
    },
    "ms": {
        "title": "🕋 PINTU PAHALA ISLAM BERSATU",
        "desc": "Waktu solat untuk **{city}** dikesan secara automatik",
        "prayer_title": "🕒 Waktu Solat Hari Ini:",
        "prayer_header": "Bandar: {city} | Negara: {country}",
        "Fajr": "🌆 Subuh", "Dhuhr": "☀️ Zuhur", "Asr": "⛅ Asar",
        "Maghrib": "🌅 Maghrib", "Isha": "🌌 Isyak",
        "quran_title": "📖 Ayat & Renungan:",
        "hadith_title": "📚 Hadis Nabi:",
        "dhikr_title": "📿 Zikir:",
        "tafsir": "Tafsir",
        "footer": "Kesanan automatik: Melayu | Tarikh: {date}",
    },
}

FALLBACK_LANG = "ar"


def _detect_lang(guild):
    locale = str(guild.preferred_locale) if guild and guild.preferred_locale else "ar"
    for key in sorted(LOCALES.keys(), key=len, reverse=True):
        if locale.startswith(key):
            return key
    return FALLBACK_LANG


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.content = self._load_content()
        self.session = None

    def _load_content(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    async def _fetch_prayer_times(self, city, country):
        url = f"{PRAYER_API}?city={city}&country={country}&method={PRAYER_METHOD}"
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("timings", {})
        except:
            return None

    def _get_random_item(self, category, field=None):
        items = self.content.get(category, [])
        if not items:
            return None
        item = random.choice(items)
        if isinstance(item, dict) and field:
            return item.get(field, str(item))
        return item

    @commands.command(name="اجر")
    async def ajr(self, ctx):
        guild = ctx.guild
        lang_key = _detect_lang(guild)
        L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])

        city, country = LOCALE_CITY_MAP.get(
            str(guild.preferred_locale) if guild else "",
            ("Makkah", "SA")
        )
        for key in sorted(LOCALE_CITY_MAP.keys(), key=len, reverse=True):
            locale_str = str(guild.preferred_locale) if guild else ""
            if locale_str.startswith(key[:2]):
                city, country = LOCALE_CITY_MAP[key]
                break

        await ctx.typing()
        timings = await self._fetch_prayer_times(city, country)
        ayah_item = self._get_random_item("ayat")
        hadith = self._get_random_item("ahadith")
        dhikr = self._get_random_item("adhkar_morning")

        embed = discord.Embed(
            title=L["title"],
            description=L["desc"].format(city=city),
            color=0x107c41
        )

        if timings:
            prayers_text = (
                f"{L['prayer_header'].format(city=city, country=country)}\n"
                f"• {L['Fajr']}: `{timings.get('Fajr', '---')}` | {L['Dhuhr']}: `{timings.get('Dhuhr', '---')}`\n"
                f"• {L['Asr']}: `{timings.get('Asr', '---')}` | {L['Maghrib']}: `{timings.get('Maghrib', '---')}`\n"
                f"• {L['Isha']}: `{timings.get('Isha', '---')}`"
            )
        else:
            prayers_text = f"⚠️ {L['prayer_header'].format(city=city, country=country)}"
        embed.add_field(name=L["prayer_title"], value=prayers_text, inline=False)

        if ayah_item:
            embed.add_field(
                name=L["quran_title"],
                value=f"*{ayah_item['text']}*\n**{L['tafsir']}:** {ayah_item.get('tafsir', '')}"[:1024],
                inline=False
            )
        if hadith:
            embed.add_field(name=L["hadith_title"], value=hadith[:1024], inline=False)
        if dhikr:
            embed.add_field(name=L["dhikr_title"], value=dhikr[:1024], inline=False)

        now = datetime.now(timezone.utc) + timedelta(hours=3)
        embed.set_footer(text=L["footer"].format(date=now.strftime("%Y-%m-%d")))
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Egr(bot))
