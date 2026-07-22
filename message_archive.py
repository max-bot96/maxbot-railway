import sqlite3
import json
import os
import time as time_module
import asyncio
import io
import discord
from datetime import datetime, timezone
from discord.ext import commands
from discord.ui import View

DB_PATH = "message_archive.db"
MAX_MESSAGES_PER_GUILD = 50000
_archive_lock = asyncio.Lock()
_archive_ratelimit = {}

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_archive_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            channel_name TEXT NOT NULL DEFAULT '',
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL DEFAULT '',
            author_display TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            attachments TEXT NOT NULL DEFAULT '[]',
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_guild ON messages(guild_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(timestamp)
    """)
    conn.commit()
    conn.close()

def archive_message(message):
    if message.author.bot:
        return
    now = time_module.time()
    last = _archive_ratelimit.get(message.author.id, 0)
    if now - last < 1:
        return
    _archive_ratelimit[message.author.id] = now
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO messages (message_id, guild_id, channel_id, channel_name, author_id, author_name, author_display, content, attachments, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.id,
                message.guild.id if message.guild else 0,
                message.channel.id,
                message.channel.name if hasattr(message.channel, 'name') else '',
                message.author.id,
                str(message.author),
                message.author.display_name,
                message.content or '',
                json.dumps([a.url for a in message.attachments]),
                message.created_at.isoformat() if message.created_at else datetime.now(timezone.utc).isoformat()
            )
        )
        conn.commit()
        conn.close()
        _cleanup_if_needed(message.guild.id if message.guild else 0)
    except Exception as e:
        print(f"[ARCHIVE ERROR] {e}")

def _cleanup_if_needed(guild_id):
    if not guild_id:
        return
    try:
        conn = get_connection()
        cnt = conn.execute("SELECT COUNT(*) FROM messages WHERE guild_id = ?", (guild_id,)).fetchone()[0]
        if cnt > MAX_MESSAGES_PER_GUILD:
            excess = cnt - MAX_MESSAGES_PER_GUILD
            conn.execute(
                "DELETE FROM messages WHERE id IN (SELECT id FROM messages WHERE guild_id = ? ORDER BY id ASC LIMIT ?)",
                (guild_id, excess)
            )
            conn.commit()
        conn.close()
    except:
        pass

def search_messages(guild_id, author_id=None, channel_id=None, query=None, limit=20, offset=0):
    conn = get_connection()
    parts = ["guild_id = ?"]
    params = [guild_id]
    if author_id:
        parts.append("author_id = ?")
        params.append(author_id)
    if channel_id:
        parts.append("channel_id = ?")
        params.append(channel_id)
    if query:
        parts.append("content LIKE ?")
        params.append(f"%{query}%")
    sql = f"SELECT * FROM messages WHERE {' AND '.join(parts)} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def count_messages(guild_id, author_id=None, channel_id=None):
    conn = get_connection()
    parts = ["guild_id = ?"]
    params = [guild_id]
    if author_id:
        parts.append("author_id = ?")
        params.append(author_id)
    if channel_id:
        parts.append("channel_id = ?")
        params.append(channel_id)
    cnt = conn.execute(f"SELECT COUNT(*) FROM messages WHERE {' AND '.join(parts)}", params).fetchone()[0]
    conn.close()
    return cnt

def purge_author(guild_id, author_id):
    conn = get_connection()
    deleted = conn.execute("DELETE FROM messages WHERE guild_id = ? AND author_id = ?", (guild_id, author_id)).rowcount
    conn.commit()
    conn.close()
    return deleted

def get_all_authors(guild_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT author_id, author_name, author_display, COUNT(*) as cnt FROM messages WHERE guild_id = ? GROUP BY author_id ORDER BY cnt DESC",
        (guild_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def generate_export(guild_id, author_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE guild_id = ? AND author_id = ? ORDER BY timestamp ASC",
        (guild_id, author_id)
    ).fetchall()
    conn.close()
    lines = []
    for r in rows:
        r = dict(r)
        ts = r["timestamp"][:19] if r["timestamp"] else "---"
        attach = json.loads(r["attachments"]) if r.get("attachments") else []
        line = f"[{ts}] #{r['channel_name']} | {r['author_name']}: {r['content']}"
        if attach:
            line += f"\n   📎 {', '.join(attach)}"
        lines.append(line)
    return "\n".join(lines)

class ArchiveSearchView(View):
    def __init__(self, guild_id, author_id, author_name, channel_id, query, page=0):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.author_id = author_id
        self.author_name = author_name
        self.channel_id = channel_id
        self.query = query
        self.page = page
        self.per_page = 10
        self.total = count_messages(guild_id, author_id=author_id, channel_id=channel_id)
        self.max_page = max(0, (self.total - 1) // self.per_page)
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if self.page > 0:
            self.add_item(ArchivePrevButton())
        self.add_item(ArchiveRefreshButton())
        text = f"📄 {self.page + 1}/{self.max_page + 1}"
        self.add_item(ArchivePageLabel(text))
        if self.page < self.max_page:
            self.add_item(ArchiveNextButton())

    async def build_embed(self, interaction):
        offset = self.page * self.per_page
        results = search_messages(
            self.guild_id,
            author_id=self.author_id,
            channel_id=self.channel_id,
            query=self.query,
            limit=self.per_page,
            offset=offset
        )
        embed = discord.Embed(
            title=f"📜 أرشيف الرسائل — {self.author_name}",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"صفحة {self.page + 1} من {self.max_page + 1} · إجمالي {self.total}")
        if not results:
            embed.description = "لا توجد رسائل"
            return embed
        desc_lines = []
        for r in results:
            chan = f"#{r['channel_name']}" if r['channel_name'] else f"<#{r['channel_id']}>"
            ts = r['timestamp'][:16] if r['timestamp'] else "---"
            content = r['content'][:150] if r['content'] else "*(بدون نص)*"
            attach = json.loads(r['attachments']) if r.get('attachments') else []
            attach_txt = f" 📎{len(attach)}" if attach else ""
            desc_lines.append(f"**{chan}** · {ts}\n{content}{attach_txt}\n─")
        embed.description = "\n".join(desc_lines)
        return embed

class ArchivePrevButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ السابق", style=discord.ButtonStyle.secondary, custom_id="archive_prev")

    async def callback(self, interaction):
        view = self.view
        view.page -= 1
        view.update_buttons()
        embed = await view.build_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

class ArchiveNextButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="التالي ▶", style=discord.ButtonStyle.secondary, custom_id="archive_next")

    async def callback(self, interaction):
        view = self.view
        view.page += 1
        view.update_buttons()
        embed = await view.build_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=view)

class ArchiveRefreshButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔄 تحديث", style=discord.ButtonStyle.primary, custom_id="archive_refresh")

    async def callback(self, interaction):
        embed = await self.view.build_embed(interaction)
        await interaction.response.edit_message(embed=embed, view=self.view)

class ArchivePageLabel(discord.ui.Button):
    def __init__(self, text):
        super().__init__(label=text, style=discord.ButtonStyle.gray, disabled=True, custom_id="archive_page")

    async def callback(self, interaction):
        pass

class ArchiveCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    archive_group = discord.app_commands.Group(name="archive", description="📜 أرشيف المحادثات")

    @archive_group.command(name="user", description="عرض رسائل عضو معين")
    @discord.app_commands.default_permissions(administrator=True)
    async def archive_user(self, interaction: discord.Interaction, member: discord.Member, limit: int = 20):
        await interaction.response.defer(ephemeral=True)
        total = count_messages(interaction.guild.id, author_id=member.id)
        if total == 0:
            return await interaction.followup.send(f"🚫 لا توجد رسائل محفوظة لـ {member.mention}", ephemeral=True)
        results = search_messages(interaction.guild.id, author_id=member.id, limit=min(limit, 50))
        embed = discord.Embed(
            title=f"📜 رسائل {member.display_name}",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"إجمالي {total} رسالة · آخر {len(results)}")
        desc_lines = []
        for r in results:
            chan = f"#{r['channel_name']}" if r['channel_name'] else f"<#{r['channel_id']}>"
            ts = r['timestamp'][:16] if r['timestamp'] else "---"
            content = r['content'][:200] if r['content'] else "*(بدون نص)*"
            attach = json.loads(r['attachments']) if r.get('attachments') else []
            attach_txt = f" 📎{len(attach)}" if attach else ""
            desc_lines.append(f"**{chan}** · {ts}\n{content}{attach_txt}\n─")
        embed.description = "\n".join(desc_lines[:30])
        await interaction.followup.send(embed=embed, ephemeral=True)

    @archive_group.command(name="channel", description="عرض رسائل روم معين")
    @discord.app_commands.default_permissions(administrator=True)
    async def archive_channel(self, interaction: discord.Interaction, channel: discord.TextChannel, limit: int = 20):
        await interaction.response.defer(ephemeral=True)
        total = count_messages(interaction.guild.id, channel_id=channel.id)
        if total == 0:
            return await interaction.followup.send(f"🚫 لا توجد رسائل محفوظة في {channel.mention}", ephemeral=True)
        results = search_messages(interaction.guild.id, channel_id=channel.id, limit=min(limit, 50))
        embed = discord.Embed(
            title=f"📜 رسائل #{channel.name}",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"إجمالي {total} رسالة · آخر {len(results)}")
        desc_lines = []
        for r in results:
            ts = r['timestamp'][:16] if r['timestamp'] else "---"
            content = r['content'][:200] if r['content'] else "*(بدون نص)*"
            attach = json.loads(r['attachments']) if r.get('attachments') else []
            attach_txt = f" 📎{len(attach)}" if attach else ""
            desc_lines.append(f"**{r['author_name']}** · {ts}\n{content}{attach_txt}\n─")
        embed.description = "\n".join(desc_lines[:30])
        await interaction.followup.send(embed=embed, ephemeral=True)

    @archive_group.command(name="search", description="بحث في أرشيف الرسائل")
    @discord.app_commands.default_permissions(administrator=True)
    async def archive_search(self, interaction: discord.Interaction, member: discord.Member = None, channel: discord.TextChannel = None, query: str = None):
        await interaction.response.defer(ephemeral=True)
        total = count_messages(
            interaction.guild.id,
            author_id=member.id if member else None,
            channel_id=channel.id if channel else None
        )
        if total == 0:
            return await interaction.followup.send("🚫 لا توجد رسائل تطابق البحث", ephemeral=True)
        view = ArchiveSearchView(
            interaction.guild.id,
            author_id=member.id if member else None,
            author_name=member.display_name if member else "الكل",
            channel_id=channel.id if channel else None,
            query=query
        )
        embed = await view.build_embed(interaction)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @archive_group.command(name="export", description="تصدير رسائل عضو كملف")
    @discord.app_commands.default_permissions(administrator=True)
    async def archive_export(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        total = count_messages(interaction.guild.id, author_id=member.id)
        if total == 0:
            return await interaction.followup.send(f"🚫 لا توجد رسائل محفوظة لـ {member.mention}", ephemeral=True)
        text = generate_export(interaction.guild.id, member.id)
        buf = io.BytesIO(text.encode('utf-8-sig'))
        file = discord.File(buf, filename=f"archive-{member.display_name}.txt")
        embed = discord.Embed(
            title=f"📦 تصدير أرشيف {member.display_name}",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        embed.description = f"إجمالي {total} رسالة"
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)

    @archive_group.command(name="purge", description="مسح أرشيف رسائل عضو")
    @discord.app_commands.default_permissions(administrator=True)
    async def archive_purge(self, interaction: discord.Interaction, member: discord.Member):
        deleted = purge_author(interaction.guild.id, member.id)
        embed = discord.Embed(
            title="🗑️ تم المسح",
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc)
        )
        embed.description = f"تم حذف **{deleted}** رسالة من أرشيف {member.mention}"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @archive_group.command(name="stats", description="إحصائيات الأرشيف")
    @discord.app_commands.default_permissions(administrator=True)
    async def archive_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        total = count_messages(interaction.guild.id)
        authors = get_all_authors(interaction.guild.id)
        embed = discord.Embed(
            title="📊 إحصائيات الأرشيف",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        embed.description = f"إجمالي الرسائل: **{total}**\nالأعضاء المسجلين: **{len(authors)}**"
        top = authors[:10]
        if top:
            lines = []
            for a in top:
                lines.append(f"• **{a['author_display']}** — {a['cnt']} رسالة")
            embed.add_field(name="🏆 أكثر 10 أعضاء", value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    init_archive_db()
    await bot.add_cog(ArchiveCommands(bot))
