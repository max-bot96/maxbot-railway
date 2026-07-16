import discord
from discord.ext import commands, tasks
import json
import os
import random
import aiohttp
import asyncio
import pytz
from datetime import datetime, timezone, timedelta

DATA_FILE = "bot_data.json"
PRAYER_API = "https://api.aladhan.com/v1/timingsByCity"
PRAYER_METHOD = 4
DATABASE_URL = os.getenv("DATABASE_URL")

ADHAN_DUA = 'ترديد الأذان مع المؤذن، ثم الصلاة على النبي ﷺ والدعاء: "اللهم رب هذه الدعوة التامة، والصلاة القائمة، آتِ محمداً الوسيلة والفضيلة، وابعثه مقاماً محموداً الذي وعدته"'
SAJDAH_HADITH = '«أَقْرَبُ مَا يَكُونُ الْعَبْدُ مِنْ رَبِّهِ وَهُوَ سَاجِدٌ، فَأَكْثِرُوا الدُّعَاءَ»'

CITY_LANG_MAP = {
    "SA": "ar", "AE": "ar", "EG": "ar", "DZ": "ar", "MA": "ar", "TN": "ar",
    "IQ": "ar", "JO": "ar", "SY": "ar", "SD": "ar", "LY": "ar",
    "TR": "tr", "CY": "tr",
    "FR": "fr", "BE": "fr", "CH": "fr",
    "DE": "de", "AT": "de",
    "ES": "es", "MX": "es",
    "BR": "pt", "PT": "pt",
    "RU": "ru",
    "ID": "id", "MY": "ms",
    "PK": "ur", "IN": "ur",
    "IR": "fa",
    "CN": "zh", "JP": "ja", "KR": "ko", "TH": "th",
    "NL": "nl", "SE": "sv", "PL": "pl", "GR": "el",
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
        "prayer_alert": "📢 @everyone | حان الآن موعد أذان **{prayer}** في **{city}** 🕌",
        "city_set": "✅ تم ضبط السيرفر على مدينة: **{city}** وتفعيل التنبيهات التلقائية 🕌",
        "city_prompt": "❌ اكتب اسم المدينة: `!المدينة مكة` أو `!المدينة القاهرة` أو `!المدينة London`",
        "city_not_found": "❌ لم يتم العثور على المدينة. تأكد من الاسم.",
        "active_on": "✅ تم تفعيل الإرسال التلقائي في {channel}",
        "active_off": "🔴 تم إيقاف الإرسال التلقائي",
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
        "prayer_alert": "📢 @everyone | Prayer time: **{prayer}** in **{city}** 🕌",
        "city_set": "✅ Server set to: **{city}** with auto reminders enabled 🕌",
        "city_prompt": "❌ Enter a city: `!المدينة Makkah` or `!المدينة Cairo` or `!المدينة London`",
        "city_not_found": "❌ City not found. Check the name.",
        "active_on": "✅ Auto reminders enabled in {channel}",
        "active_off": "🔴 Auto reminders disabled",
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
        "prayer_alert": "📢 @everyone | **{prayer}** vakti girdi - **{city}** 🕌",
        "city_set": "✅ Sunucu **{city}** olarak ayarlandı, otomatik bildirimler aktif 🕌",
        "city_prompt": "❌ Şehir yazın: `!المدينة İstanbul` veya `!المدينة Ankara`",
        "city_not_found": "❌ Şehir bulunamadı.",
        "active_on": "✅ Otomatik bildirimler {channel} kanalında aktif",
        "active_off": "🔴 Otomatik bildirimler devre dışı",
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
        "prayer_alert": "📢 @everyone | Heure de la prière **{prayer}** à **{city}** 🕌",
        "city_set": "✅ Serveur configuré sur **{city}** avec rappels automatiques 🕌",
        "city_prompt": "❌ Entrez une ville: `!المدينة Paris` ou `!المدينة Mecca`",
        "city_not_found": "❌ Ville introuvable.",
        "active_on": "✅ Rappels automatiques activés dans {channel}",
        "active_off": "🔴 Rappels automatiques désactivés",
    },
}

FALLBACK_LANG = "en"


def _detect_lang(country_code):
    lang = CITY_LANG_MAP.get(country_code)
    if lang and lang in LOCALES:
        return lang
    return FALLBACK_LANG


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.content = self._load_content()
        self.session = None
        self.pool = None
        self.use_db = False
        self.prayer_cache = {}
        self._cache_ttl = {}

    def _load_content(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    # ── Storage ──

    async def _init_storage(self):
        if DATABASE_URL:
            try:
                import asyncpg
                self.pool = await asyncpg.create_pool(DATABASE_URL)
                async with self.pool.acquire() as conn:
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS server_configs (
                            guild_id BIGINT PRIMARY KEY,
                            city VARCHAR(100) DEFAULT 'Makkah',
                            country VARCHAR(10) DEFAULT 'SA',
                            city_name VARCHAR(100) DEFAULT 'مكة المكرمة',
                            channel_id BIGINT,
                            hourly_active BOOLEAN DEFAULT FALSE
                        )
                    ''')
                self.use_db = True
                print("[EGR] ✅ PostgreSQL connected", flush=True)
            except Exception as e:
                print(f"[EGR] ❌ PostgreSQL failed: {e}", flush=True)

    async def _get_config(self, guild_id):
        if self.use_db and self.pool:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow('SELECT * FROM server_configs WHERE guild_id = $1', guild_id)
                    if row:
                        return dict(row)
                    await conn.execute('INSERT INTO server_configs (guild_id) VALUES ($1) ON CONFLICT DO NOTHING', guild_id)
            except:
                pass
        data = load_data()
        return data.get("egr", {}).get(str(guild_id), {})

    async def _save_config(self, guild_id, config):
        if self.use_db and self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO server_configs (guild_id, city, country, city_name, channel_id, hourly_active)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (guild_id) DO UPDATE SET
                            city = $2, country = $3, city_name = $4,
                            channel_id = $5, hourly_active = $6
                    ''', guild_id, config.get("city", "Makkah"), config.get("country", "SA"),
                       config.get("city_name", "مكة المكرمة"),
                       config.get("channel_id"), config.get("hourly_active", False))
                return
            except:
                pass
        data = load_data()
        if "egr" not in data:
            data["egr"] = {}
        data["egr"][str(guild_id)] = config
        save_data(data)

    async def _get_all_configs(self):
        if self.use_db and self.pool:
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch('SELECT * FROM server_configs')
                    return [dict(r) for r in rows]
            except:
                pass
        data = load_data()
        return [{"guild_id": int(k), **v} for k, v in data.get("egr", {}).items()]

    # ── Prayer API ──

    async def _fetch_prayer_data(self, city):
        url = f"{PRAYER_API}?city={city}&method={PRAYER_METHOD}"
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
        except:
            return None

    async def _get_city_country(self, city):
        data = await self._fetch_prayer_data(city)
        if data and data.get("data"):
            meta = data["data"].get("meta", {})
            country = (meta.get("latitude", "") + "," + meta.get("longitude", ""))
            return {
                "timings": data["data"]["timings"],
                "timezone": meta.get("timezone", "UTC"),
                "city": city,
                "country": meta.get("method", {}).get("name", city)
            }
        return None

    def _get_random_item(self, category, field=None):
        items = self.content.get(category, [])
        if not items:
            return None
        item = random.choice(items)
        if isinstance(item, dict) and field:
            return item.get(field, str(item))
        return item

    # ── Background: Prayer Checker ──

    @tasks.loop(seconds=30)
    async def prayer_checker(self):
        await self.bot.wait_until_ready()
        configs = await self._get_all_configs()
        for cfg in configs:
            channel_id = cfg.get("channel_id")
            city = cfg.get("city")
            if not channel_id or not city:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue

            data = await self._fetch_prayer_data(city)
            if not data or not data.get("data"):
                continue

            timings = data["data"]["timings"]
            meta = data["data"].get("meta", {})
            tz_str = meta.get("timezone", "UTC")

            try:
                local_tz = pytz.timezone(tz_str)
                local_now = datetime.now(local_tz)
                current = local_now.strftime("%H:%M")
            except:
                continue

            for prayer_key in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
                prayer_time = timings.get(prayer_key)
                if not prayer_time or prayer_time != current:
                    continue

                cache_key = f"{cfg['guild_id']}_{prayer_key}_{local_now.strftime('%Y-%m-%d')}"
                if self._cache_ttl.get(cache_key):
                    continue
                self._cache_ttl[cache_key] = True
                if len(self._cache_ttl) > 500:
                    self._cache_ttl.clear()

                country = cfg.get("country", "SA")
                lang_key = _detect_lang(country)
                L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])
                prayer_label = L.get(prayer_key, prayer_key)
                city_name = cfg.get("city_name", city)

                embed = discord.Embed(
                    title=f"🕋 {prayer_label}",
                    description=f"**{city_name}** - {local_now.strftime('%Y-%m-%d %H:%M')}",
                    color=0x107c41
                )
                embed.add_field(name="📖 الذكر عند سماع الأذان", value=ADHAN_DUA, inline=False)
                embed.add_field(name="💡 أثر صلاتك", value=f"*{SAJDAH_HADITH}*", inline=False)

                try:
                    await channel.send(
                        content=L["prayer_alert"].format(prayer=prayer_label, city=city_name),
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(everyone=True)
                    )
                except:
                    pass

    # ── Background: Hourly Sender ──

    @tasks.loop(hours=1)
    async def hourly_sender(self):
        await self.bot.wait_until_ready()
        configs = await self._get_all_configs()
        for cfg in configs:
            if not cfg.get("hourly_active"):
                continue
            channel_id = cfg.get("channel_id")
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue

            pool = []
            for item in self.content.get("adhkar_morning", []):
                pool.append(("🌅 أذكار", item, "ar"))
            for item in self.content.get("adhkar_evening", []):
                pool.append(("🌆 أذكار المساء", item, "ar"))
            for item in self.content.get("duas", []):
                pool.append(("🤲 دعاء", item, "ar"))
            if not pool:
                continue

            label, text, _ = random.choice(pool)
            embed = discord.Embed(title=label, description=str(text)[:1024], color=0x107c41,
                                  timestamp=datetime.now(timezone.utc))
            embed.set_footer(text="🕌 تذكير تلقائي | كل ساعة")
            try:
                await channel.send(embed=embed)
            except:
                pass

    # ── The ONE Command ──

    @commands.command(name="اجر")
    async def ajr(self, ctx):
        config = await self._get_config(ctx.guild.id)
        city = config.get("city", "Makkah")
        country = config.get("country", "SA")
        city_name = config.get("city_name", city)

        lang_key = _detect_lang(country)
        L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])

        await ctx.typing()

        data = await self._fetch_prayer_data(city)
        timings = data["data"]["timings"] if data and data.get("data") else None

        ayah_item = self._get_random_item("ayat")
        hadith = self._get_random_item("ahadith")
        dhikr = self._get_random_item("adhkar_morning")

        embed = discord.Embed(
            title=L["title"],
            description=L["desc"].format(city=city_name),
            color=0x107c41
        )

        if timings:
            prayers_text = (
                f"{L['prayer_header'].format(city=city_name, country=country)}\n"
                f"• {L['Fajr']}: `{timings.get('Fajr', '---')}` | {L['Dhuhr']}: `{timings.get('Dhuhr', '---')}`\n"
                f"• {L['Asr']}: `{timings.get('Asr', '---')}` | {L['Maghrib']}: `{timings.get('Maghrib', '---')}`\n"
                f"• {L['Isha']}: `{timings.get('Isha', '---')}`"
            )
        else:
            prayers_text = f"⚠️ {L['prayer_header'].format(city=city_name, country=country)}"
        embed.add_field(name=L["prayer_title"], value=prayers_text, inline=False)

        if ayah_item:
            embed.add_field(name=L["quran_title"],
                            value=f"*{ayah_item['text']}*\n**{L['tafsir']}:** {ayah_item.get('tafsir', '')}"[:1024],
                            inline=False)
        if hadith:
            embed.add_field(name=L["hadith_title"], value=hadith[:1024], inline=False)
        if dhikr:
            embed.add_field(name=L["dhikr_title"], value=dhikr[:1024], inline=False)

        now = datetime.now(timezone.utc) + timedelta(hours=3)
        config_str = "PostgreSQL" if self.use_db else "JSON"
        embed.set_footer(text=f"{L['footer'].format(date=now.strftime('%Y-%m-%d'))} | {config_str}")
        await ctx.send(embed=embed)

    # ── City Setup ──

    @commands.command(name="المدينة")
    async def set_city(self, ctx, *, city_name=None):
        if not city_name:
            config = await self._get_config(ctx.guild.id)
            lang_key = _detect_lang(config.get("country", "SA"))
            L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])
            current_city = config.get("city_name", config.get("city", "غير معروف"))
            await ctx.send(f"ℹ️ المدينة الحالية: **{current_city}**\n{L['city_prompt']}")
            return

        data = await self._fetch_prayer_data(city_name)
        if not data or not data.get("data"):
            config = await self._get_config(ctx.guild.id)
            lang_key = _detect_lang(config.get("country", "SA"))
            L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])
            await ctx.send(f"{L['city_not_found']} مثال: `!المدينة Makkah` / `!المدينة London` / `!المدينة İstanbul`")
            return

        meta = data["data"].get("meta", {})
        tz_str = meta.get("timezone", "UTC")
        country_code = "SA"
        known_cities = {"Makkah": "SA", "Jeddah": "SA", "Riyadh": "SA", "Medina": "SA", "المدينة": "SA",
                        "Cairo": "EG", "Alexandria": "EG", "القاهرة": "EG",
                        "Dubai": "AE", "Abu Dhabi": "AE", "دبي": "AE",
                        "London": "GB", "Manchester": "GB",
                        "New York": "US", "Los Angeles": "US", "Chicago": "US",
                        "Paris": "FR", "Berlin": "DE", "Istanbul": "TR", "İstanbul": "TR",
                        "Ankara": "TR", "Rome": "IT", "Madrid": "ES",
                        "Moscow": "RU", "Beijing": "CN", "Tokyo": "JP",
                        "Jakarta": "ID", "Kuala Lumpur": "MY", "Karachi": "PK",
                        "Mumbai": "IN", "Delhi": "IN", "Dhaka": "BD",
                        "Tehran": "IR", "Baghdad": "IQ", "Amman": "JO",
                        "Damascus": "SY", "Beirut": "LB", "Khartoum": "SD",
                        "Algiers": "DZ", "Tunis": "TN", "Rabat": "MA",
                        "Sydney": "AU", "Toronto": "CA", "São Paulo": "BR",
                        "Rio de Janeiro": "BR", "Lisbon": "PT"}
        country_code = known_cities.get(city_name, "SA")
        if "Asia/Riyadh" in tz_str or "Arabia" in tz_str:
            country_code = "SA"
        elif "Africa/Cairo" in tz_str or "Egypt" in tz_str:
            country_code = "EG"
        elif "Asia/Dubai" in tz_str:
            country_code = "AE"
        elif "Europe/London" in tz_str:
            country_code = "GB"
        elif "America/New_York" in tz_str:
            country_code = "US"
        elif "Europe/Paris" in tz_str:
            country_code = "FR"
        elif "Europe/Berlin" in tz_str:
            country_code = "DE"
        elif "Europe/Istanbul" in tz_str or "Asia/Istanbul" in tz_str:
            country_code = "TR"
        elif "Europe/Moscow" in tz_str:
            country_code = "RU"
        elif "Asia/Jakarta" in tz_str:
            country_code = "ID"
        elif "Asia/Karachi" in tz_str:
            country_code = "PK"
        elif "Asia/Tehran" in tz_str:
            country_code = "IR"
        elif "Asia/Baghdad" in tz_str:
            country_code = "IQ"

        lang_key = _detect_lang(country_code)
        L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])

        config = await self._get_config(ctx.guild.id)
        config["city"] = city_name
        config["country"] = country_code
        config["city_name"] = city_name
        config["channel_id"] = ctx.channel.id
        await self._save_config(ctx.guild.id, config)

        await ctx.send(f"✅ **{city_name}** 🕋\n🌍 {tz_str}\n{L['city_set'].format(city=city_name)}")

    # ── Toggle Auto ──

    @commands.command(name="تلقائي")
    async def auto_toggle(self, ctx, *, mode=None):
        config = await self._get_config(ctx.guild.id)
        lang_key = _detect_lang(config.get("country", "SA"))
        L = LOCALES.get(lang_key, LOCALES[FALLBACK_LANG])

        if mode not in ["تشغيل", "إيقاف", "on", "off"]:
            await ctx.send(f"{L['city_prompt']}")
            return

        if mode in ["تشغيل", "on"]:
            config["channel_id"] = ctx.channel.id
            config["hourly_active"] = True
            await self._save_config(ctx.guild.id, config)
            await ctx.send(L["active_on"].format(channel=ctx.channel.mention))
        else:
            config["hourly_active"] = False
            await self._save_config(ctx.guild.id, config)
            await ctx.send(L["active_off"])

    def cog_unload(self):
        self.prayer_checker.cancel()
        self.hourly_sender.cancel()

    async def cog_load(self):
        await self._init_storage()
        self.prayer_checker.start()
        self.hourly_sender.start()


async def setup(bot):
    await bot.add_cog(Egr(bot))
