import discord
from discord.ext import commands, tasks
import json
import os
import random
import aiohttp
import asyncio
import pytz
from datetime import datetime

PRAYER_API = "https://api.aladhan.com/v1/timingsByCity"
PRAYER_METHOD = 4

GLOBAL_ZONES = [
    {"city": "Makkah", "country": "SA", "zone": "Asia/Riyadh", "locale_key": "ar"},
    {"city": "Cairo", "country": "EG", "zone": "Africa/Cairo", "locale_key": "ar"},
    {"city": "Istanbul", "country": "TR", "zone": "Europe/Istanbul", "locale_key": "tr"},
    {"city": "London", "country": "GB", "zone": "Europe/London", "locale_key": "en"},
    {"city": "New York", "country": "US", "zone": "America/New_York", "locale_key": "en"},
    {"city": "Jakarta", "country": "ID", "zone": "Asia/Jakarta", "locale_key": "id"},
    {"city": "Rabat", "country": "MA", "zone": "Africa/Casablanca", "locale_key": "ar"},
    {"city": "Paris", "country": "FR", "zone": "Europe/Paris", "locale_key": "fr"},
    {"city": "Berlin", "country": "DE", "zone": "Europe/Berlin", "locale_key": "de"},
    {"city": "Moscow", "country": "RU", "zone": "Europe/Moscow", "locale_key": "ru"},
    {"city": "Karachi", "country": "PK", "zone": "Asia/Karachi", "locale_key": "ur"},
    {"city": "Tehran", "country": "IR", "zone": "Asia/Tehran", "locale_key": "fa"},
    {"city": "Kuala Lumpur", "country": "MY", "zone": "Asia/Kuala_Lumpur", "locale_key": "ms"},
    {"city": "Baghdad", "country": "IQ", "zone": "Asia/Baghdad", "locale_key": "ar"},
    {"city": "Tokyo", "country": "JP", "zone": "Asia/Tokyo", "locale_key": "ja"},
    {"city": "Sydney", "country": "AU", "zone": "Australia/Sydney", "locale_key": "en"},
    {"city": "São Paulo", "country": "BR", "zone": "America/Sao_Paulo", "locale_key": "pt"},
    {"city": "Delhi", "country": "IN", "zone": "Asia/Kolkata", "locale_key": "en"},
    {"city": "Dhaka", "country": "BD", "zone": "Asia/Dhaka", "locale_key": "bn"},
    {"city": "Algiers", "country": "DZ", "zone": "Africa/Algiers", "locale_key": "ar"},
]

PRAYER_KEYS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
PRAYER_NAMES = {"ar": ["الفجر", "الظهر", "العصر", "المغرب", "العشاء"],
                "en": ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
                "tr": ["İmsak", "Öğle", "İkindi", "Akşam", "Yatsı"],
                "fr": ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
                "de": ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
                "id": ["Subuh", "Dzuhur", "Ashar", "Maghrib", "Isya"],
                "ms": ["Subuh", "Zuhur", "Asar", "Maghrib", "Isyak"],
                "ur": ["فجر", "ظہر", "عصر", "مغرب", "عشاء"],
                "fa": ["صبح", "ظهر", "عصر", "مغرب", "عشا"],
                "ru": ["Фаджр", "Зухр", "Аср", "Магриб", "Иша"],
                "pt": ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"],
                "bn": ["ফজর", "যোহর", "আসর", "মাগরিব", "ইশা"],
                "ja": ["ファジル", "ズフル", "アスル", "マグリブ", "イシャ"]}

TZ_LOCALE_MAP = {}
for z in GLOBAL_ZONES:
    TZ_LOCALE_MAP[z["zone"]] = z["locale_key"]

ADHAN_DUA = 'ترديد الأذان مع المؤذن، ثم الصلاة على النبي ﷺ والدعاء: "اللهم رب هذه الدعوة التامة، والصلاة القائمة، آتِ محمداً الوسيلة والفضيلة، وابعثه مقاماً محموداً الذي وعدته"'
SAJDAH_HADITH = '«أَقْرَبُ مَا يَكُونُ الْعَبْدُ مِنْ رَبِّهِ وَهُوَ سَاجِدٌ، فَأَكْثِرُوا الدُّعَاءَ»'

ALERTS_SENT = {}


def load_content():
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def pick_random(items):
    if not items:
        return None
    return random.choice(items)


def detect_locale(guild):
    locale = str(guild.preferred_locale) if guild and guild.preferred_locale else ""
    for z in GLOBAL_ZONES:
        if z["country"].lower() in locale.lower() or locale.startswith(z["locale_key"]):
            return z["locale_key"]
    return "ar"


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.content = load_content()
        self.session = None
        self._prayer_cache = {}

    async def _get_prayer_times(self, city, country):
        url = f"{PRAYER_API}?city={city}&country={country}&method={PRAYER_METHOD}"
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    timings = data.get("data", {}).get("timings", {})
                    timezone = data.get("data", {}).get("meta", {}).get("timezone", "UTC")
                    return timings, timezone
        except:
            pass
        return None, None

    def _get_prayer_name(self, lang_key, index):
        names = PRAYER_NAMES.get(lang_key, PRAYER_NAMES["en"])
        if index < len(names):
            return names[index]
        return PRAYER_KEYS[index]

    # ── Auto Hourly Adhkar/Duas ──

    @tasks.loop(hours=1)
    async def auto_hourly(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            channel = guild.system_channel or next(
                (ch for ch in guild.text_channels
                 if ch.permissions_for(guild.me).send_messages and
                 ch.permissions_for(guild.me).embed_links),
                None
            )
            if not channel:
                continue

            pool = []
            for item in self.content.get("adhkar_morning", []):
                pool.append(("🌅 أذكار", item))
            for item in self.content.get("adhkar_evening", []):
                pool.append(("🌆 أذكار المساء", item))
            for item in self.content.get("duas", []):
                pool.append(("🤲 دعاء", item))
            if not pool:
                continue
            label, text = random.choice(pool)

            embed = discord.Embed(
                title=label,
                description=str(text)[:1024],
                color=0x107c41,
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="🕌 تذكير تلقائي كل ساعة")

            if random.random() < 0.3:
                ayah = pick_random(self.content.get("ayat"))
                if ayah:
                    embed.add_field(name="📖 آية وتدبر",
                                    value=f"*{ayah.get('text', '')}*\n{ayah.get('tafsir', '')}"[:1024],
                                    inline=False)
            try:
                await channel.send(embed=embed)
                await asyncio.sleep(0.3)
            except:
                pass

    # ── Auto Global Prayer Scanner ──

    @tasks.loop(minutes=1)
    async def auto_prayer_scanner(self):
        await self.bot.wait_until_ready()
        for zone in GLOBAL_ZONES:
            timings, tz_str = await self._get_prayer_times(zone["city"], zone["country"])
            if not timings:
                continue

            try:
                tz_obj = pytz.timezone(zone["zone"])
                now_local = datetime.now(tz_obj)
                current = now_local.strftime("%H:%M")
            except:
                continue

            for i, key in enumerate(PRAYER_KEYS):
                prayer_time = timings.get(key)
                if not prayer_time or prayer_time != current:
                    continue

                today = now_local.strftime("%Y-%m-%d")
                dedup_key = f"{zone['city']}_{key}_{today}"
                if ALERTS_SENT.get(dedup_key):
                    continue
                ALERTS_SENT[dedup_key] = True
                if len(ALERTS_SENT) > 1000:
                    ALERTS_SENT.clear()

                lang_key = zone["locale_key"]
                prayer_label = self._get_prayer_name(lang_key, i)

                embed = discord.Embed(
                    title=f"🕌 {prayer_label} - {zone['city']}",
                    description=f"{now_local.strftime('%Y-%m-%d %H:%M')} {tz_str}",
                    color=0x107c41
                )
                embed.add_field(name="📖 الذكر عند سماع الأذان", value=ADHAN_DUA, inline=False)
                embed.add_field(name="💡 أثر صلاتك", value=f"*{SAJDAH_HADITH}*", inline=False)
                embed.set_footer(text=f"🌍 {zone['city']} | توقيت تلقائي")

                for guild in self.bot.guilds:
                    glocale = detect_locale(guild)
                    if glocale != lang_key:
                        continue
                    channel = guild.system_channel or next(
                        (ch for ch in guild.text_channels
                         if ch.permissions_for(guild.me).send_messages and
                         ch.permissions_for(guild.me).embed_links),
                        None
                    )
                    if not channel:
                        continue
                    try:
                        await channel.send(
                            content=f"📢 @everyone | **{prayer_label}** - {zone['city']} 🕌",
                            embed=embed,
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )
                        await asyncio.sleep(0.5)
                    except:
                        pass

    def cog_unload(self):
        self.auto_hourly.cancel()
        self.auto_prayer_scanner.cancel()

    async def cog_load(self):
        self.auto_hourly.start()
        self.auto_prayer_scanner.start()


async def setup(bot):
    await bot.add_cog(Egr(bot))
