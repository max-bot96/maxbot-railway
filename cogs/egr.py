import discord
from discord.ext import commands, tasks
import json
import os
import random
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta

DATA_FILE = "bot_data.json"
PRAYER_API = "https://api.aladhan.com/v1/timingsByCity"
PRAYER_METHOD = 4

ADHAN_DUA = 'ترديد الأذان مع المؤذن، ثم الصلاة على النبي ﷺ والدعاء: "اللهم رب هذه الدعوة التامة، والصلاة القائمة، آتِ محمداً الوسيلة والفضيلة، وابعثه مقاماً محموداً الذي وعدته"'
SAJDAH_HADITH = '«أَقْرَبُ مَا يَكُونُ الْعَبْدُ مِنْ رَبِّهِ وَهُوَ سَاجِدٌ، فَأَكْثِرُوا الدُّعَاءَ»'

PRAYER_NAMES = {
    "Fajr": "الفجر", "Sunrise": "الشروق", "Dhuhr": "الظهر",
    "Asr": "العصر", "Maghrib": "المغرب", "Isha": "العشاء"
}

DEFAULT_CITIES = [
    {"name": "مكة المكرمة", "city": "Makkah", "country": "SA"},
    {"name": "القاهرة", "city": "Cairo", "country": "EG"},
    {"name": "دبي", "city": "Dubai", "country": "AE"},
    {"name": "الرباط", "city": "Rabat", "country": "MA"},
    {"name": "الجزائر", "city": "Algiers", "country": "DZ"},
    {"name": "تونس", "city": "Tunis", "country": "TN"},
    {"name": "بغداد", "city": "Baghdad", "country": "IQ"},
    {"name": "عمّان", "city": "Amman", "country": "JO"},
    {"name": "الخرطوم", "city": "Khartoum", "country": "SD"},
    {"name": "دمشق", "city": "Damascus", "country": "SY"},
]

HOURLY_TYPES = [
    "adhkar", "ayah", "hadith", "names", "dua", "benefit", "story", "adhkar_evening"
]


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
    except Exception as e:
        print(f"[EGR] Save error: {e}", flush=True)


class Egr(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.content = self._load_content()
        self.prayer_cache = {}
        self.hourly_index = 0
        self.last_prayers_sent = {}
        self.session = None

    def _load_content(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[EGR] Content load error: {e}", flush=True)
            return {}

    def _get_config(self, guild_id):
        data = load_data()
        return data.get("egr", {}).get(str(guild_id), {})

    def _save_config(self, guild_id, config):
        data = load_data()
        if "egr" not in data:
            data["egr"] = {}
        data["egr"][str(guild_id)] = config
        save_data(data)

    async def _fetch_prayer_times(self, city, country):
        url = f"{PRAYER_API}?city={city}&country={country}&method={PRAYER_METHOD}"
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("timings", {})
        except Exception as e:
            print(f"[EGR] API error for {city}: {e}", flush=True)
        return None

    async def update_all_prayer_times(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"prayer_{today}"
        if hasattr(self, "_prayer_cache_day") and self._prayer_cache_day == cache_key:
            return
        self.prayer_cache = {}
        for loc in DEFAULT_CITIES:
            timings = await self._fetch_prayer_times(loc["city"], loc["country"])
            if timings:
                self.prayer_cache[loc["name"]] = timings
                print(f"[EGR] Prayer times loaded: {loc['name']}", flush=True)
            await asyncio.sleep(0.5)
        self._prayer_cache_day = cache_key
        print(f"[EGR] Prayer cache updated: {len(self.prayer_cache)} cities", flush=True)

    def _get_random_item(self, category, field=None):
        items = self.content.get(category, [])
        if not items:
            return None
        item = random.choice(items)
        if isinstance(item, dict) and field:
            return item.get(field, str(item))
        return item

    # ── Background Tasks ──
    @tasks.loop(hours=1)
    async def hourly_sender(self):
        await self.bot.wait_until_ready()
        data = load_data()
        egr_data = data.get("egr", {})
        for guild_id_str, config in egr_data.items():
            if not config.get("active", False):
                continue
            channel_id = config.get("channel_id")
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue
            idx = config.get("hourly_index", 0)
            types = HOURLY_TYPES
            t = types[idx % len(types)]
            if t == "adhkar":
                items = self.content.get("adhkar_morning", [])
                label = "🌅 أذكار الصباح"
            elif t == "adhkar_evening":
                items = self.content.get("adhkar_evening", [])
                label = "🌆 أذكار المساء"
            elif t == "ayah":
                item = self._get_random_item("ayat")
                items = [f"{item['text']}\n*{item.get('tafsir', '')}*"] if item else []
                label = "📖 آية وتفسير"
            elif t == "hadith":
                items = self.content.get("ahadith", [])
                label = "📚 حديث نبوي"
            elif t == "names":
                item = self._get_random_item("names_of_allah")
                items = [f"**{item['name']}**\n{item['meaning']}"] if item else []
                label = "ﷲ اسم من أسماء الله الحسنى"
            elif t == "dua":
                items = self.content.get("duas", [])
                label = "🤲 دعاء"
            elif t == "benefit":
                items = self.content.get("benefits", [])
                label = "💡 فائدة دينية"
            elif t == "story":
                items = self.content.get("stories", [])
                label = "📖 قصة إسلامية"
            else:
                items = self.content.get("adhkar_morning", [])
                label = "🌅 أذكار"
            if not items:
                continue
            text = random.choice(items) if isinstance(items, list) else items
            text = str(text)[:1024]
            embed = discord.Embed(
                title=label,
                description=text,
                color=0x107c41,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="🕌 تذكير تلقائي | كل ساعة")
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"[EGR] Send error guild {guild_id_str}: {e}", flush=True)
            config["hourly_index"] = (idx + 1) % len(HOURLY_TYPES)
            egr_data[guild_id_str] = config
            data["egr"] = egr_data
            save_data(data)

    @tasks.loop(minutes=1)
    async def prayer_checker(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        current_min = now.minute
        if current_hour == 0 and current_min == 0:
            await self.update_all_prayer_times()
        if not self.prayer_cache:
            await self.update_all_prayer_times()
        data = load_data()
        egr_data = data.get("egr", {})
        for guild_id_str, config in egr_data.items():
            if not config.get("active", False):
                continue
            channel_id = config.get("channel_id")
            if not channel_id:
                continue
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            for loc_name, timings in self.prayer_cache.items():
                for prayer_key, prayer_label in PRAYER_NAMES.items():
                    if prayer_key == "Sunrise":
                        continue
                    time_str = timings.get(prayer_key, "")
                    if not time_str:
                        continue
                    parts = time_str.split(":")
                    if len(parts) != 2:
                        continue
                    p_hour, p_min = int(parts[0]), int(parts[1])
                    if current_hour == p_hour and current_min == p_min:
                        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        send_key = f"{guild_id_str}_{loc_name}_{prayer_key}_{today}"
                        if self.last_prayers_sent.get(send_key):
                            continue
                        self.last_prayers_sent[send_key] = True
                        self.last_prayers_sent = {k: v for k, v in list(self.last_prayers_sent.items())[-200:]}
                        await self._send_prayer_reminder(channel, guild, prayer_key, prayer_label, loc_name)

    async def _send_prayer_reminder(self, channel, guild, prayer_key, prayer_label, loc_name):
        now = datetime.now(timezone.utc)
        arabic_weekdays = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
        weekday_ar = arabic_weekdays[now.weekday()]
        months_ar = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
        date_str = f"{weekday_ar}، {now.day} {months_ar[now.month-1]} {now.year}"

        embed = discord.Embed(
            title=f"🕋 حَانَ الآنَ مَوْعِدُ أَذَانِ صَلَاةِ {prayer_label}",
            description="حسب التوقيت المحلي للمنطقة المذكورة أدناه، أرحنا بها يا بلال.",
            color=0x107c41
        )
        embed.set_author(name="🕌 تَذْكِيرٌ بِالصَّلَاةِ", icon_url=guild.icon.url if guild.icon else None)
        embed.add_field(name="🕒 تفاصيل التوقيت", value="══════════════", inline=False)
        embed.add_field(name="🌍 المنطقة والدولة", value=f"` {loc_name} `", inline=True)
        embed.add_field(name="🔹 الفريضة الحالية", value=f"` صلاة {prayer_label} `", inline=True)
        embed.add_field(name="📅 التاريخ اليوم", value=f"` {date_str} `", inline=False)
        embed.add_field(name="📖 الذكر المأثور عند سماع الأذان", value=ADHAN_DUA, inline=False)
        embed.add_field(name="💡 أثر صلاتك", value=f"*{SAJDAH_HADITH}*", inline=False)
        embed.set_footer(text=f"🗓️ اليوم: {now.strftime('%d/%m/%Y')} | ⌚ الوقت الحالي حسب توقيت البوت")
        embed.timestamp = now

        try:
            await channel.send(
                content=f"📢 @everyone | تذكير بإقامة صلاة **{prayer_label}** في **{loc_name}**",
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )
        except Exception as e:
            print(f"[EGR] Prayer send error: {e}", flush=True)

    # ── The ONE Command ──
    @commands.command(name="اجر")
    async def ajr_unified(self, ctx):
        config = self._get_config(ctx.guild.id)
        city = config.get("city", "Makkah")
        country = config.get("country", "SA")
        city_name = config.get("city_name", "مكة المكرمة")

        await ctx.typing()

        timings = await self._fetch_prayer_times(city, country)

        ayah_item = self._get_random_item("ayat")
        hadith = self._get_random_item("ahadith")
        dhikr = self._get_random_item("adhkar_morning")

        now = datetime.now(timezone.utc) + timedelta(hours=3)
        today_str = now.strftime("%Y-%m-%d")

        embed = discord.Embed(
            title="🕋 بَوَّابَةُ الأَجْرِ الإِسْلَامِيَّةُ الُموَحَّدَةُ",
            description="جميع الأذكار والمواقيت والنفحات الإيمانية في شاشة واحدة.",
            color=0x107c41
        )

        prayers_text = "**المدينة:** " + city_name + "\n"
        if timings:
            prayers_text += (
                f"• 🌆 الفجر: `{timings.get('Fajr', '---')}` | ☀️ الظهر: `{timings.get('Dhuhr', '---')}`\n"
                f"• ⛅ العصر: `{timings.get('Asr', '---')}` | 🌅 المغرب: `{timings.get('Maghrib', '---')}`\n"
                f"• 🌌 العشاء: `{timings.get('Isha', '---')}`"
            )
        else:
            prayers_text += "⚠️ تعذر جلب أوقات الصلاة"
        embed.add_field(name="🕒 مواقيت الصلاة اليوم:", value=prayers_text, inline=False)

        if ayah_item:
            ayah_text = ayah_item.get("text", "")
            ayah_tafsir = ayah_item.get("tafsir", "")
            ayah_str = f"*{ayah_text}*\n**التفسير:** {ayah_tafsir}"
            embed.add_field(name="📖 آية وتدبر اليوم:", value=ayah_str[:1024], inline=False)

        if hadith:
            embed.add_field(name="📚 من مشكاة النبوة (حديث شريف):", value=hadith[:1024], inline=False)

        if dhikr:
            embed.add_field(name="📿 ذكر وتذكير الساعة:", value=dhikr[:1024], inline=False)

        active_status = "🟢 مفعل" if config.get("active") else "🔴 غير مفعل"
        embed.add_field(
            name="⚙️ الإعدادات",
            value=f"الإرسال التلقائي: {active_status}\n"
                  f"`!المدينة [الاسم]` - تغيير المدينة\n"
                  f"`!تلقائي تشغيل` - تفعيل التذكير\n"
                  f"`!تلقائي إيقاف` - إيقاف التذكير",
            inline=False
        )

        embed.set_footer(text=f"تاريخ العرض: {today_str} | البوت يعمل بنظام الجدولة الآلية كل ساعة وعند كل صلاة.")
        await ctx.send(embed=embed)

    # ── Settings Commands ──
    @commands.command(name="المدينة")
    async def set_city(self, ctx, *, city_name=None):
        if not city_name:
            names = "\n".join([f"• {c['name']} ({c['city']})" for c in DEFAULT_CITIES])
            await ctx.send(f"❌ اكتب اسم المدينة. المدن المتاحة:\n{names}")
            return
        valid = [c for c in DEFAULT_CITIES if city_name in c["name"] or city_name.lower() in c["city"].lower()]
        if not valid:
            names = "\n".join([f"• {c['name']} ({c['city']})" for c in DEFAULT_CITIES])
            await ctx.send(f"❌ المدينة غير موجودة. المدن المتاحة:\n{names}")
            return
        loc = valid[0]
        config = self._get_config(ctx.guild.id)
        config["city"] = loc["city"]
        config["country"] = loc["country"]
        config["city_name"] = loc["name"]
        self._save_config(ctx.guild.id, config)
        await ctx.send(f"✅ تم تعيين المدينة: **{loc['name']}**")

    @commands.command(name="تلقائي")
    async def auto_toggle(self, ctx, *, mode=None):
        if mode not in ["تشغيل", "إيقاف"]:
            await ctx.send("❌ استخدم: `!تلقائي تشغيل` أو `!تلقائي إيقاف`")
            return
        config = self._get_config(ctx.guild.id)
        if mode == "تشغيل":
            config["active"] = True
            config["channel_id"] = ctx.channel.id
            if "city" not in config:
                config["city"] = "Makkah"
                config["country"] = "SA"
                config["city_name"] = "مكة المكرمة"
            if "hourly_index" not in config:
                config["hourly_index"] = 0
            self._save_config(ctx.guild.id, config)
            await ctx.send(f"✅ تم تفعيل الإرسال التلقائي في {ctx.channel.mention}")
        else:
            config["active"] = False
            self._save_config(ctx.guild.id, config)
            await ctx.send("🔴 تم إيقاف الإرسال التلقائي")

    @tasks.loop(hours=24)
    async def daily_prayer_update(self):
        await self.update_all_prayer_times()

    def cog_unload(self):
        self.hourly_sender.cancel()
        self.prayer_checker.cancel()
        self.daily_prayer_update.cancel()

    async def cog_load(self):
        self.hourly_sender.start()
        self.prayer_checker.start()
        self.daily_prayer_update.start()
        self.bot.loop.create_task(self.update_all_prayer_times())


async def setup(bot):
    await bot.add_cog(Egr(bot))
