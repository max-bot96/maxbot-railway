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
    "ar": "Makkah", "ar_SA": "Makkah", "ar_AE": "Dubai", "ar_EG": "Cairo",
    "ar_DZ": "Algiers", "ar_MA": "Rabat", "ar_TN": "Tunis", "ar_IQ": "Baghdad",
    "ar_JO": "Amman", "ar_SY": "Damascus", "ar_SD": "Khartoum", "ar_LY": "Tripoli",
    "en_US": "New York", "en_GB": "London", "en_CA": "Toronto", "en_AU": "Sydney",
    "en_IN": "Mumbai", "en_PH": "Manila", "en_NG": "Lagos", "en_ZA": "Cape Town",
    "en_KE": "Nairobi", "en_PK": "Karachi", "en_BD": "Dhaka",
    "fr_FR": "Paris", "fr_BE": "Brussels", "fr_CH": "Geneva",
    "de_DE": "Berlin", "de_AT": "Vienna", "de_CH": "Zurich",
    "tr_TR": "Istanbul", "tr_CY": "Nicosia",
    "es_ES": "Madrid", "es_MX": "Mexico City", "es_AR": "Buenos Aires",
    "pt_BR": "Brasilia", "pt_PT": "Lisbon",
    "ru_RU": "Moscow", "zh_CN": "Beijing", "ja_JP": "Tokyo",
    "id_ID": "Jakarta", "ms_MY": "Kuala Lumpur", "bn_BD": "Dhaka",
    "ur_PK": "Karachi", "fa_IR": "Tehran", "sw_KE": "Nairobi",
    "hi_IN": "Mumbai", "ta_IN": "Chennai", "te_IN": "Hyderabad",
    "ko_KR": "Seoul", "th_TH": "Bangkok", "vi_VN": "Ho Chi Minh City",
    "nl_NL": "Rotterdam", "sv_SE": "Stockholm", "no_NO": "Oslo",
    "da_DK": "Copenhagen", "fi_FI": "Helsinki", "pl_PL": "Warsaw",
    "cs_CZ": "Prague", "hu_HU": "Budapest", "el_GR": "Athens",
    "ro_RO": "Bucharest", "bg_BG": "Sofia", "sr_RS": "Belgrade",
    "uk_UA": "Kyiv", "he_IL": "Jerusalem", "ar_IL": "Jerusalem",
}

COUNTRY_OVERRIDES = {
    "Makkah": "SA", "Dubai": "AE", "Cairo": "EG", "Algiers": "DZ",
    "Rabat": "MA", "Tunis": "TN", "Baghdad": "IQ", "Amman": "JO",
    "Damascus": "SY", "Khartoum": "SD", "Tripoli": "LY", "New York": "US",
    "London": "GB", "Toronto": "CA", "Sydney": "AU", "Mumbai": "IN",
    "Manila": "PH", "Lagos": "NG", "Cape Town": "ZA", "Nairobi": "KE",
    "Karachi": "PK", "Dhaka": "BD", "Paris": "FR", "Brussels": "BE",
    "Geneva": "CH", "Berlin": "DE", "Vienna": "AT", "Zurich": "CH",
    "Istanbul": "TR", "Nicosia": "CY", "Madrid": "ES", "Mexico City": "MX",
    "Buenos Aires": "AR", "Brasilia": "BR", "Lisbon": "PT",
    "Moscow": "RU", "Beijing": "CN", "Tokyo": "JP", "Jakarta": "ID",
    "Kuala Lumpur": "MY", "Tehran": "IR", "Chennai": "IN",
    "Hyderabad": "IN", "Seoul": "KR", "Bangkok": "TH",
    "Ho Chi Minh City": "VN", "Rotterdam": "NL", "Stockholm": "SE",
    "Oslo": "NO", "Copenhagen": "DK", "Helsinki": "FI", "Warsaw": "PL",
    "Prague": "CZ", "Budapest": "HU", "Athens": "GR", "Bucharest": "RO",
    "Sofia": "BG", "Belgrade": "RS", "Kyiv": "UA", "Jerusalem": "IL",
}


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

    def _detect_city(self, guild):
        locale = str(guild.preferred_locale) if guild and guild.preferred_locale else "ar"
        city = LOCALE_CITY_MAP.get(locale)
        if city:
            return city, COUNTRY_OVERRIDES.get(city, "SA")
        for key in sorted(LOCALE_CITY_MAP.keys(), key=len, reverse=True):
            if locale.startswith(key[:2]):
                city = LOCALE_CITY_MAP[key]
                return city, COUNTRY_OVERRIDES.get(city, "SA")
        return "Makkah", "SA"

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
        city, country = self._detect_city(guild)

        await ctx.typing()

        timings = await self._fetch_prayer_times(city, country)
        ayah_item = self._get_random_item("ayat")
        hadith = self._get_random_item("ahadith")
        dhikr = self._get_random_item("adhkar_morning")

        locale = str(guild.preferred_locale) if guild and guild.preferred_locale else "ar"
        locale_display = {"ar": "العربية", "en": "English", "fr": "Français"}.get(locale[:2], locale[:2])

        embed = discord.Embed(
            title="🕋 بَوَّابَةُ الأَجْرِ الإِسْلَامِيَّةُ الُموَحَّدَةُ",
            description=f"النفحات الإيمانية والمواقيت الفورية لـ **{city}**",
            color=0x107c41
        )

        if timings:
            prayers_text = (
                f"**المدينة:** {city} | **الدولة:** {country}\n"
                f"• 🌆 الفجر: `{timings.get('Fajr', '---')}` | ☀️ الظهر: `{timings.get('Dhuhr', '---')}`\n"
                f"• ⛅ العصر: `{timings.get('Asr', '---')}` | 🌅 المغرب: `{timings.get('Maghrib', '---')}`\n"
                f"• 🌌 العشاء: `{timings.get('Isha', '---')}`"
            )
        else:
            prayers_text = f"⚠️ تعذر جلب مواقيت {city}"
        embed.add_field(name="🕒 مواقيت الصلاة اليوم:", value=prayers_text, inline=False)

        if ayah_item:
            embed.add_field(name="📖 آية وتدبر اليوم:",
                            value=f"*{ayah_item['text']}*\n**التفسير:** {ayah_item.get('tafsir', '')}"[:1024],
                            inline=False)
        if hadith:
            embed.add_field(name="📚 من مشكاة النبوة (حديث شريف):", value=hadith[:1024], inline=False)
        if dhikr:
            embed.add_field(name="📿 ذكر وتذكير الساعة:", value=dhikr[:1024], inline=False)

        now = datetime.now(timezone.utc) + timedelta(hours=3)
        embed.set_footer(text=f"تم الكشف التلقائي: {locale_display} | التاريخ: {now.strftime('%Y-%m-%d')}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Egr(bot))
