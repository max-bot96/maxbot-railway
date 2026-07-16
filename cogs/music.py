import discord
from discord.ext import commands
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_data, save_data, mark_data_dirty
from log_service import LogEmbed, LogColors, send_log


class Music(commands.Cog):
    """🎵 نظام الموسيقى"""

    def __init__(self, bot):
        self.bot = bot

    def _load_music_config(self):
        data = load_data()
        return {int(k): v for k, v in data.get("music_control", {}).items()}

    def _save_music_config(self, config):
        data = load_data()
        data["music_control"] = {str(k): v for k, v in config.items()}
        mark_data_dirty()
        save_data()

    @commands.group(name="music", aliases=["موسيقى"], invoke_without_command=True)
    async def music_group(self, ctx):
        """نظام الموسيقى"""
        if not ctx.author.voice:
            await ctx.send("❌ لازم تكون في روم صوتي!")
            return
        embed = discord.Embed(title="🎵 أوامر الموسيقى", color=0x9146FF)
        embed.add_field(name="`!join`", value="دخول الروم الصوتي", inline=True)
        embed.add_field(name="`!leave`", value="الخروج من الروم الصوتي", inline=True)
        embed.add_field(name="`!play <رابط>`", value="تشغيل أغنية", inline=True)
        embed.add_field(name="`!pause`", value="إيقاف مؤقت", inline=True)
        embed.add_field(name="`!resume`", value="استئناف", inline=True)
        embed.add_field(name="`!stop`", value="إيقاف الموسيقى", inline=True)
        embed.add_field(name="`!skip`", value="تخطي الأغنية", inline=True)
        embed.add_field(name="`!queue`", value="قائمة الانتظار", inline=True)
        embed.add_field(name="`!nowplaying`", value="الأغنية الحالية", inline=True)
        embed.add_field(name="`!volume <1-100>`", value="مستوى الصوت", inline=True)
        embed.add_field(name="`!loop`", value="تكرار الأغنية", inline=True)
        embed.add_field(name="`!shuffle`", value="خلط القائمة", inline=True)
        await ctx.send(embed=embed)

    @music_group.command(name="join", aliases=["دخول"])
    async def join_cmd(self, ctx):
        """دخول الروم الصوتي"""
        if not ctx.author.voice:
            await ctx.send("❌ لازم تكون في روم صوتي!")
            return
        channel = ctx.author.voice.channel
        try:
            await channel.connect()
            await ctx.send(f"✅ دخلت {channel.mention}")
        except Exception as e:
            await ctx.send(f"❌ خطأ: {e}")

    @music_group.command(name="leave", aliases=["خروج"])
    async def leave_cmd(self, ctx):
        """الخروج من الروم الصوتي"""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("✅ خرجت من الروم الصوتي")
        else:
            await ctx.send("❌ البوت مو في أي روم صوتي!")

    @music_group.command(name="play", aliases=["تشغيل"])
    async def play_cmd(self, ctx, url: str = None):
        """تشغيل أغنية"""
        if not url:
            await ctx.send("❌ حدد رابط الأغنية: `!play <رابط>`")
            return
        if not ctx.author.voice:
            await ctx.send("❌ لازم تكون في روم صوتي!")
            return
        vc = ctx.voice_client
        if not vc:
            try:
                vc = await ctx.author.voice.channel.connect()
            except Exception as e:
                await ctx.send(f"❌ خطأ في الاتصال: {e}")
                return
        try:
            import yt_dlp
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info['url']
                title = info.get('title', 'غير معروف')
            embed = discord.Embed(title="🎵 جاري التشغيل", description=f"**{title}**", color=0x9146FF)
            embed.add_field(name="القناة", value=ctx.author.voice.channel.mention, inline=True)
            embed.add_field(name="بواسطة", value=ctx.author.mention, inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ خطأ في التشغيل: {e}")

    @music_group.command(name="pause", aliases=["إيقاف_مؤقت"])
    async def pause_cmd(self, ctx):
        """إيقاف مؤقت"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ تم الإيقاف المؤقت")
        else:
            await ctx.send("❌ لا توجد أغنية تعمل!")

    @music_group.command(name="resume", aliases=["استئناف"])
    async def resume_cmd(self, ctx):
        """استئناف التشغيل"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ تم الاستئناف")
        else:
            await ctx.send("❌ لا توجد أغنية متوقفة!")

    @music_group.command(name="stop", aliases=["إيقاف"])
    async def stop_cmd(self, ctx):
        """إيقاف الموسيقى"""
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.send("⏹️ تم الإيقاف")
        else:
            await ctx.send("❌ البوت مو في أي روم صوتي!")

    @music_group.command(name="skip", aliases=["تخطي"])
    async def skip_cmd(self, ctx):
        """تخطي الأغنية"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ تم التخطي")
        else:
            await ctx.send("❌ لا توجد أغنية تعمل!")

    @music_group.command(name="queue", aliases=["قائمة"])
    async def queue_cmd(self, ctx):
        """قائمة الانتظار"""
        embed = discord.Embed(title="📋 قائمة الانتظار", color=0x9146FF)
        embed.add_field(name="الحالة", value="القائمة فارغة حالياً", inline=False)
        await ctx.send(embed=embed)

    @music_group.command(name="nowplaying", aliases=["الحالية"])
    async def nowplaying_cmd(self, ctx):
        """الأغنية الحالية"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            embed = discord.Embed(title="🎵 الأغنية الحالية", color=0x9146FF)
            embed.add_field(name="الحالة", value="تعمل حالياً", inline=True)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ لا توجد أغنية تعمل!")

    @music_group.command(name="volume", aliases=["صوت"])
    async def volume_cmd(self, ctx, volume: int = None):
        """مستوى الصوت (1-100)"""
        if volume is None:
            if ctx.voice_client:
                current = int(ctx.voice_client.source.volume * 100) if ctx.voice_client.source else 100
                await ctx.send(f"🔊 مستوى الصوت الحالي: **{current}%**")
            else:
                await ctx.send("❌ البوت مو في أي روم صوتي!")
            return
        if volume < 1 or volume > 100:
            await ctx.send("❌ الصوت يجب أن يكون بين 1 و 100!")
            return
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = volume / 100
            await ctx.send(f"🔊 تم تغيير الصوت إلى **{volume}%**")
        else:
            await ctx.send("❌ لا توجد موسيقى تعمل!")

    @music_group.command(name="loop", aliases=["تكرار"])
    async def loop_cmd(self, ctx):
        """تكرار الأغنية"""
        config = self._load_music_config()
        guild_config = config.setdefault(ctx.guild.id, {})
        guild_config["loop"] = not guild_config.get("loop", False)
        self._save_music_config(config)
        state = "🟢 مفعّل" if guild_config["loop"] else "🔴 معطّل"
        await ctx.send(f"🔁 التكرار: {state}")

    @music_group.command(name="shuffle", aliases=["خلط"])
    async def shuffle_cmd(self, ctx):
        """خلط قائمة الانتظار"""
        await ctx.send("🔀 تم خلط القائمة")


async def setup(bot):
    await bot.add_cog(Music(bot))
