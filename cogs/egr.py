import discord
from discord.ext import commands, tasks
import json
import os
import random
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta

DATA_FILE = "bot_data.json"
CONTENT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "islamic_content.json")
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

    def _get_hourly_content(self, index):
        if not self.content:
            return None, "لا توجد بيانات"
        types = HOURLY_TYPES
        t = types[index % len(types)]
        if t == "adhkar":
            items = self.content.get("adhkar_morning", [])
            label = "🌅 أذكار الصباح"
        elif t == "adhkar_evening":
            items = self.content.get("adhkar_evening", [])
            label = "🌆 أذكار المساء"
        elif t == "ayah":
            items = self.content.get("ayat", [])
            label = "📖 آية وتفسير"
        elif t == "hadith":
            items = self.content.get("ahadith", [])
            label = "📚 حديث نبوي"
        elif t == "names":
            items = self.content.get("names_of_allah", [])
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
            return None, "لا توجد محتوى"
        item = random.choice(items)
        if isinstance(item, dict):
            if "text" in item:
                text = item["text"]
                if t == "ayah":
                    text += f"\nسورة {item.get('surah', '')} آية {item.get('ayah', '')}"
                    if item.get("tafsir"):
                        text += f"\n\n📝 **التفسير:** {item['tafsir']}"
                elif t == "names":
                    text = f"**{item['name']}**\n{item['meaning']}"
            else:
                text = str(item)
        else:
            text = str(item)
        return label, text

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
            await asyncio.sleep(1)
        self._prayer_cache_day = cache_key
        print(f"[EGR] Prayer cache updated: {len(self.prayer_cache)} cities", flush=True)

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
            label, text = self._get_hourly_content(idx)
            if not label:
                continue
            embed = discord.Embed(
                title=label,
                description=text[:1024] if len(text) > 1024 else text,
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
                        send_key = f"{guild_id_str}_{loc_name}_{prayer_key}_{today_str()}"
                        if self.last_prayers_sent.get(send_key):
                            continue
                        self.last_prayers_sent[send_key] = True
                        self.last_prayers_sent = {k: v for k, v in list(self.last_prayers_sent.items())[-200:]}
                        await self._send_prayer_reminder(channel, guild, prayer_key, prayer_label, loc_name)

    async def _send_prayer_reminder(self, channel, guild, prayer_key, prayer_label, loc_name):
        timings = self.prayer_cache.get(loc_name, {})
        now = datetime.now(timezone.utc) + timedelta(hours=3)
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

    # ── Commands ──
    @commands.command(name="اجر")
    async def ajr_main(self, ctx):
        embed = discord.Embed(
            title="🕌 بسم الله الرحمن الرحيم",
            description="أهلاً بك في نظام **الأجر** - تذكير دائم بالله",
            color=0x107c41
        )
        embed.add_field(name="📋 الأوامر المتاحة", value="""
        `!اجر المدينة [الاسم]` - تعيين المدينة
        `!اجر اذكار` - أذكار الصباح والمساء
        `!اجر اية` - آية قرآنية مع التفسير
        `!اجر حديث` - حديث نبوي شريف
        `!اجر صلاه` - أوقات الصلاة اليوم
        """, inline=False)
        embed.add_field(name="⚙️ للإعداد", value="`!اجر تفعيل` - تفعيل الإرسال التلقائي\n`!اجر تعطيل` - إيقاف الإرسال التلقائي", inline=False)
        embed.set_footer(text="ﷲ لا إله إلا الله")
        await ctx.send(embed=embed)

    @commands.command(name="اجر_المدينة")
    async def ajr_city(self, ctx, *, city_name=None):
        if not city_name:
            await ctx.send("❌ اكتب اسم المدينة: `!اجر المدينة مكة`")
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

    @commands.command(name="اجر_تفعيل")
    @commands.has_permissions(administrator=True)
    async def ajr_enable(self, ctx):
        config = self._get_config(ctx.guild.id)
        config["active"] = True
        config["channel_id"] = ctx.channel.id
        if "city" not in config:
            config["city"] = "Makkah"
            config["country"] = "SA"
            config["city_name"] = "مكة المكرمة"
        if "hourly_index" not in config:
            config["hourly_index"] = 0
        self._save_config(ctx.guild.id, config)
        await ctx.send(f"✅ تم تفعيل نظام الأجر في {ctx.channel.mention}")

    @commands.command(name="اجر_تعطيل")
    @commands.has_permissions(administrator=True)
    async def ajr_disable(self, ctx):
        config = self._get_config(ctx.guild.id)
        config["active"] = False
        self._save_config(ctx.guild.id, config)
        await ctx.send("🔴 تم إيقاف نظام الأجر")

    @commands.command(name="اجر_اذكار")
    async def ajr_adhkar(self, ctx):
        embed = discord.Embed(title="🌅 أذكار الصباح", color=0x107c41)
        items = self.content.get("adhkar_morning", [])[:5]
        for i, item in enumerate(items, 1):
            embed.add_field(name=f"ذكر {i}", value=item[:200], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="اجر_اية")
    async def ajr_ayah(self, ctx):
        items = self.content.get("ayat", [])
        if not items:
            await ctx.send("❌ لا توجد بيانات")
            return
        item = random.choice(items)
        embed = discord.Embed(
            title=f"📖 {item['text']}",
            description=f"سورة **{item['surah']}** آية {item['ayah']}",
            color=0x107c41
        )
        embed.add_field(name="📝 التفسير", value=item.get("tafsir", "")[:1024], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="اجر_حديث")
    async def ajr_hadith(self, ctx):
        items = self.content.get("ahadith", [])
        if not items:
            await ctx.send("❌ لا توجد بيانات")
            return
        hadith = random.choice(items)
        embed = discord.Embed(
            title="📚 حديث نبوي شريف",
            description=hadith[:1024],
            color=0x107c41
        )
        await ctx.send(embed=embed)

    @commands.command(name="اجر_صلاه")
    async def ajr_prayer(self, ctx):
        config = self._get_config(ctx.guild.id)
        city = config.get("city", "Makkah")
        country = config.get("country", "SA")
        city_name = config.get("city_name", "مكة المكرمة")
        await ctx.send("🕋 جاري جلب أوقات الصلاة...")
        timings = await self._fetch_prayer_times(city, country)
        if not timings:
            await ctx.send("❌ تعذر جلب أوقات الصلاة")
            return
        now = datetime.now(timezone.utc) + timedelta(hours=3)
        embed = discord.Embed(
            title=f"🕌 أوقات الصلاة - {city_name}",
            description=f"📅 اليوم: {now.strftime('%Y-%m-%d')}",
            color=0x107c41
        )
        for key, label in PRAYER_NAMES.items():
            if key == "Sunrise":
                embed.add_field(name="🌅 الشروق", value=timings.get(key, "---"), inline=True)
                continue
            t = timings.get(key, "---")
            p_hour, p_min = 0, 0
            if ":" in t:
                try:
                    parts = t.split(":")
                    p_hour, p_min = int(parts[0]), int(parts[1])
                except:
                    pass
            passed = "(❌ فاتت)" if (now.hour > p_hour or (now.hour == p_hour and now.min > p_min)) and key != "Sunrise" else ""
            embed.add_field(name=f"🕋 {label}", value=f"`{t}` {passed}", inline=True)
        embed.set_footer(text="🔹 توقيت مكة المكرمة")
        await ctx.send(embed=embed)

    @commands.command(name="اجر_دعاء")
    async def ajr_dua(self, ctx):
        items = self.content.get("duas", [])
        if not items:
            await ctx.send("❌ لا توجد بيانات")
            return
        dua = random.choice(items)
        embed = discord.Embed(title="🤲 دعاء", description=dua, color=0x107c41)
        await ctx.send(embed=embed)

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


def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def setup(bot):
    await bot.add_cog(Egr(bot))
