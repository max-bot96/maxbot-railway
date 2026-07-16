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
AI_API_KEY = os.getenv("AI_API_KEY")

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
                "id": ["Subuh", "Dzuhur", "Ashar", "Maghrib", "Isya"],
                "ru": ["Фаджр", "Зухр", "Аср", "Магриб", "Иша"],
                "ur": ["فجر", "ظہر", "عصر", "مغرب", "عشاء"],
                "fa": ["صبح", "ظهر", "عصر", "مغرب", "عشا"],
                "ms": ["Subuh", "Zuhur", "Asar", "Maghrib", "Isyak"],
                "bn": ["ফজর", "যোহর", "আসর", "মাগরিব", "ইশা"],
                "ja": ["ファジル", "ズフル", "アスル", "マグリブ", "イシャ"]}

ADHAN_DUA = 'ترديد الأذان مع المؤذن، ثم الصلاة على النبي ﷺ والدعاء: "اللهم رب هذه الدعوة التامة، والصلاة القائمة، آتِ محمداً الوسيلة والفضيلة، وابعثه مقاماً محموداً الذي وعدته"'
SAJDAH_HADITH = '«أَقْرَبُ مَا يَكُونُ الْعَبْدُ مِنْ رَبِّهِ وَهُوَ سَاجِدٌ، فَأَكْثِرُوا الدُّعَاءَ»'
ALERTS_SENT = {}

AI_MODEL = None
if AI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=AI_API_KEY)
        AI_MODEL = genai.GenerativeModel('gemini-pro')
        print("[EGR] ✅ Gemini AI ready", flush=True)
    except Exception as e:
        print(f"[EGR] ❌ Gemini init failed: {e}", flush=True)


def load_content():
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[EGR] Content load error: {e}", flush=True)
        return {}


def pick_random(items):
    return random.choice(items) if items else None


def detect_locale(guild):
    locale = str(guild.preferred_locale) if guild and guild.preferred_locale else ""
    for z in GLOBAL_ZONES:
        if z["country"].lower() in locale.lower() or locale.startswith(z["locale_key"]):
            return z["locale_key"]
    return "ar"


def locale_to_lang(locale_key):
    m = {"ar": "Arabic", "en": "English", "tr": "Turkish", "fr": "French",
         "de": "German", "ru": "Russian", "id": "Indonesian", "ms": "Malay",
         "ur": "Urdu", "fa": "Persian", "bn": "Bengali", "ja": "Japanese",
         "pt": "Portuguese"}
    return m.get(locale_key, "Arabic")


async def generate_ai_content(prompt, lang="Arabic"):
    if not AI_MODEL:
        return None
    try:
        full_prompt = f"Respond in {lang}.\n{prompt}"
        response = AI_MODEL.generate_content(full_prompt, generation_config={
            "max_output_tokens": 300, "temperature": 0.8
        })
        return response.text.strip() if response and response.text else None
    except Exception as e:
        print(f"[EGR] AI error: {e}", flush=True)
        return None


def find_best_channel(guild):
    ch = guild.system_channel
    if ch and ch.permissions_for(guild.me).send_messages and ch.permissions_for(guild.me).embed_links:
        return ch
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages and ch.permissions_for(guild.me).embed_links:
            return ch
    return None


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.content = load_content()
        self.session = None
        self.use_ai = AI_MODEL is not None

    async def _get_prayer_times(self, city, country):
        url = f"{PRAYER_API}?city={city}&country={country}&method={PRAYER_METHOD}"
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    t = data.get("data", {}).get("timings", {})
                    tz = data.get("data", {}).get("meta", {}).get("timezone", "UTC")
                    return t, tz
        except:
            pass
        return None, None

    def _get_prayer_name(self, lang_key, index):
        names = PRAYER_NAMES.get(lang_key, PRAYER_NAMES["en"])
        return names[index] if index < len(names) else PRAYER_KEYS[index]

    # ── AI Hourly Generator ──

    @tasks.loop(hours=1)
    async def auto_hourly(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            channel = find_best_channel(guild)
            if not channel:
                continue

            lang_key = detect_locale(guild)
            lang_name = locale_to_lang(lang_key)

            if self.use_ai:
                prompt = (
                    f"Write a beautiful, short Islamic reminder in {lang_name} ({lang_key}). "
                    f"Begin with a Quranic verse (Arabic + translation in {lang_name}), "
                    f"then give a short reflection, then a prophetic hadith or wisdom, "
                    f"then end with a short Dua. Use emojis. "
                    f"Keep it under 1000 characters. Format for Discord."
                )
                ai_text = await generate_ai_content(prompt, lang_name)
            else:
                ai_text = None

            if ai_text:
                embed = discord.Embed(
                    title="✨ نفحة إيمانية",
                    description=ai_text[:2000],
                    color=0x107c41,
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text="🕌 توليد AI | كل ساعة")
            else:
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
                embed.set_footer(text="🕌 تذكير كل ساعة")
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

    # ── AI Response on Mention ──

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if not self.bot.user.mentioned_in(message):
            return

        question = message.content.replace(f'<@{self.bot.user.id}>', '').replace(f'<@!{self.bot.user.id}>', '').strip()

        if not question:
            await message.reply(
                "🌟 أنا بوت الأجر! اسألني عن أي شيء إسلامي:\n"
                "• تفسير آية\n"
                "• حديث نبوي\n"
                "• فضل عبادة\n"
                "• دعاء\n"
                "• أحكام الصلاة"
            )
            return

        if not self.use_ai:
            await message.reply("⚠️ الذكاء الاصطناعي غير مفعل. أضف `AI_API_KEY` في Railway Variables.")
            return

        async with message.channel.typing():
            lang_key = detect_locale(message.guild)
            lang_name = locale_to_lang(lang_key)

            prompt = (
                f"You are an Islamic scholar assistant in a Discord bot. "
                f"Answer the following question in {lang_name} using Quran and Sunnah. "
                f"Be concise, accurate, and use emojis. Keep it under 1500 characters.\n\n"
                f"Question: {question}"
            )
            answer = await generate_ai_content(prompt, lang_name)

            if answer:
                embed = discord.Embed(
                    title=f"💡 {lang_name} Islamic Answer",
                    description=answer[:2000],
                    color=0x107c41
                )
                embed.set_footer(text=f"🤖 AI | سؤال: {question[:50]}")
                try:
                    await message.reply(embed=embed)
                except:
                    await message.reply(answer[:2000])
            else:
                await message.reply("⚠️ عذراً، واجهت مشكلة في توليد الرد. حاول مرة أخرى.")

    # ── !اجر Dashboard Command ──

    @commands.command(name="اجر")
    async def ajr(self, ctx):
        lang_key = detect_locale(ctx.guild)
        lang_name = locale_to_lang(lang_key)

        zone = GLOBAL_ZONES[0]
        for z in GLOBAL_ZONES:
            if z["locale_key"] == lang_key:
                zone = z
                break

        await ctx.typing()
        timings, tz_str = await self._get_prayer_times(zone["city"], zone["country"])

        embed = discord.Embed(
            title="🕋 بَوَّابَةُ الأَجْرِ الإِسْلَامِيَّةُ",
            description=f"{zone['city']} | {lang_name}",
            color=0x107c41
        )

        if timings:
            pt = (
                f"**{zone['city']}**\n"
                f"• {self._get_prayer_name(lang_key, 0)}: `{timings.get('Fajr', '---')}`\n"
                f"• {self._get_prayer_name(lang_key, 1)}: `{timings.get('Dhuhr', '---')}`\n"
                f"• {self._get_prayer_name(lang_key, 2)}: `{timings.get('Asr', '---')}`\n"
                f"• {self._get_prayer_name(lang_key, 3)}: `{timings.get('Maghrib', '---')}`\n"
                f"• {self._get_prayer_name(lang_key, 4)}: `{timings.get('Isha', '---')}`"
            )
            embed.add_field(name="🕒 Prayer Times", value=pt, inline=False)
        else:
            embed.add_field(name="🕒 Prayer Times", value="⚠️ Unavailable", inline=False)

        ayah = pick_random(self.content.get("ayat"))
        if ayah:
            embed.add_field(name="📖 Quran",
                            value=f"*{ayah.get('text', '')}*\n{ayah.get('tafsir', '')}"[:1024],
                            inline=False)

        hadith = pick_random(self.content.get("ahadith"))
        if hadith:
            embed.add_field(name="📚 Hadith", value=hadith[:1024], inline=False)

        dhikr = pick_random(self.content.get("adhkar_morning"))
        if dhikr:
            embed.add_field(name="📿 Dhikr", value=dhikr[:1024], inline=False)

        embed.set_footer(text=f"🌍 {zone['city']} | AI={'✅' if self.use_ai else '❌'}")
        await ctx.send(embed=embed)

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
                embed.add_field(name="📖 الذكر عند الأذان", value=ADHAN_DUA, inline=False)
                embed.add_field(name="💡 أثر صلاتك", value=f"*{SAJDAH_HADITH}*", inline=False)
                embed.set_footer(text=f"🌍 {zone['city']}")

                for guild in self.bot.guilds:
                    if detect_locale(guild) != lang_key:
                        continue
                    channel = find_best_channel(guild)
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
        if self.use_ai:
            print("[EGR] 🤖 AI mode active - generating unique content hourly", flush=True)
        else:
            print("[EGR] 📖 JSON mode - set AI_API_KEY for AI generation", flush=True)
        self.auto_hourly.start()
        self.auto_prayer_scanner.start()


async def setup(bot):
    await bot.add_cog(Egr(bot))
