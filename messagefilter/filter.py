from redbot.core import commands, Config, checks
import discord
from datetime import datetime
import re

class MessageFilter(commands.Cog):
    """Automatically delete messages that don't contain required words"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "channels": {},
            "active": True
        }
        self.config.register_guild(**default_guild)

    @commands.group()
    @commands.admin_or_permissions(administrator=True)
    async def filter(self, ctx):
        """Manage message filtering"""
        pass

    @filter.command()
    async def addchannel(self, ctx, channel: discord.TextChannel):
        """Add a channel to filter"""
        async with self.config.guild(ctx.guild).channels() as channels:
            if str(channel.id) not in channels:
                channels[str(channel.id)] = []
                await ctx.send(f"{channel.mention} added to filtered channels")
            else:
                await ctx.send("This channel is already being filtered")

    @filter.command()
    async def removechannel(self, ctx, channel: discord.TextChannel):
        """Stop filtering a channel"""
        async with self.config.guild(ctx.guild).channels() as channels:
            channel_id = str(channel.id)
            if channel_id in channels:
                del channels[channel_id]
                await ctx.send(f"Stopped filtering {channel.mention}")
            else:
                await ctx.send("This channel wasn't being filtered")
                
    @filter.command()
    async def addword(self, ctx, channel: discord.TextChannel = None, *, words: str):
        """Add required words for a channel"""
        channel = channel or ctx.channel
        words = [w.strip().lower() for w in words.split(", ")]
        
        async with self.config.guild(ctx.guild).channels() as channels:
            channel_id = str(channel.id)
            if channel_id not in channels:
                channels[channel_id] = []
            
            added = []
            for word in words:
                if word not in channels[channel_id]:
                    channels[channel_id].append(word)
                    added.append(word)
            
            if added:
                await ctx.send(f"Added words: {', '.join(added)}")

    @filter.command()
    async def removeword(self, ctx, channel: discord.TextChannel = None, *, words: str):
        """Remove words from a channel's required list"""
        channel = channel or ctx.channel
        words = [w.strip().lower() for w in words.split(", ")]
        
        async with self.config.guild(ctx.guild).channels() as channels:
            channel_id = str(channel.id)
            removed = []
            for word in words:
                if word in channels.get(channel_id, []):
                    channels[channel_id].remove(word)
                    removed.append(word)
            
            if removed:
                await ctx.send(f"Removed words: {', '.join(removed)}")
                
    @filter.command()
    @commands.admin_or_permissions(administrator=True)
    async def logchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel for logging filtered messages"""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Filter logs will now be sent to {channel.mention}")
        
    @filter.command()
    async def list(self, ctx):
        """Show currently filtered channels and their required words"""
        channels = await self.config.guild(ctx.guild).channels()
        embed = discord.Embed(title="Filtered Channels", color=0x00ff00)
        
        for channel_id, words in channels.items():
            channel = ctx.guild.get_channel(int(channel_id))
            if channel:
                word_list = ', '.join(f'`{word}`' for word in required_words) if required_words else "No words set"
                embed.add_field(
                    name=f"#{channel.name}",
                    value=f"Required words: {word_list}",
                    inline=False
                )
        
        if not embed.fields:
            embed.description = "No channels being filtered"
        
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        await self.check_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        await self.check_message(after)
                        
    async def check_message(self, message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.permissions_for(message.author).manage_messages:
            return
        channels = await self.config.guild(message.guild).channels()
        channel_id = str(message.channel.id)
        if channel_id in channels:
            required_words = channels[channel_id]
            if required_words:
                message_content = message.content.lower()
                regexes = [self.wildcard_to_regex(word) for word in required_words]
                if not any(regex.search(message_content) for regex in regexes):
                    try:
                        await message.delete()
                        await self.log_filtered_message(message)
                    except discord.HTTPException:
                        pass
                        
    def wildcard_to_regex(self, word):
        parts = word.split('*')
        escaped = [re.escape(part) for part in parts]
        pattern = '.*'.join(escaped)
        return re.compile(pattern)

    async def check_message(self, message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.permissions_for(message.author).administrator:
            return
        channels = await self.config.guild(message.guild).channels()
        channel_id = str(message.channel.id)
        if channel_id in channels:
            required_words = channels[channel_id]
            if required_words:
                message_content = message.content.lower()
                regexes = [self.wildcard_to_regex(word) for word in required_words]
                if not any(regex.search(message_content) for regex in regexes):
                    try:
                        await message.delete()
                        await self.log_filtered_message(message)
                    except discord.HTTPException:
                        pass

    async def log_filtered_message(self, message):
        log_channel_id = await self.config.guild(message.guild).log_channel()
        if not log_channel_id:
            return
        
        log_channel = message.guild.get_channel(log_channel_id)
        if not log_channel:
            return
        
        embed = discord.Embed(
            color=0xff0000,
            description=f"**Message sent by {message.author.mention} filtered in {message.channel.mention}**\n"
                       f"{message.content}"
        )
        embed.set_author(
            name=f"{message.author.name} ({message.author.id})",
            icon_url=message.author.display_avatar.url
        )
        embed.set_footer(
            text=f"Author: {message.author.id} | Message ID: {message.id} • {datetime.now().strftime('%b %d, %Y %I:%M %p')}"
        )
        
        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass
