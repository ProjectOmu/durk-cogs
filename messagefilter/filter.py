from redbot.core import commands, Config, checks
import discord
from datetime import datetime
from datetime import timedelta
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
    async def filter(self, ctx):
        """Manage message filtering"""
        pass

    @filter.command()
    @commands.admin_or_permissions(administrator=True)
    async def addchannel(self, ctx, channel: discord.TextChannel):
        async with self.config.guild(ctx.guild).channels() as channels:
            if str(channel.id) not in channels:
                channels[str(channel.id)] = []
                embed = discord.Embed(
                    title="✅ Channel Added",
                    description=f"{channel.mention} will now filter messages",
                    color=0x00ff00
                )
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(
                    title="⚠️ Already Filtered",
                    description=f"{channel.mention} is already being monitored",
                    color=0xffd700
                )
                await ctx.send(embed=embed)

    @filter.command()
    @commands.admin_or_permissions(administrator=True)
    async def removechannel(self, ctx, channel: discord.TextChannel):
        async with self.config.guild(ctx.guild).channels() as channels:
            channel_id = str(channel.id)
            if channel_id in channels:
                del channels[channel_id]
                embed = discord.Embed(
                    title="✅ Channel Removed",
                    description=f"Stopped filtering {channel.mention}",
                    color=0x00ff00
                )
            else:
                embed = discord.Embed(
                    title="⚠️ Not Filtered",
                    description=f"{channel.mention} wasn't being monitored",
                    color=0xffd700
                )
            await ctx.send(embed=embed)
                
    @filter.command()
    @commands.admin_or_permissions(administrator=True)
    async def addword(self, ctx, *, args: str):
        """Add required words to a channel's filter"""
        try:
            # Try to parse channel from beginning of arguments
            converter = commands.TextChannelConverter()
            channel, _, words_part = args.partition(' ')
            channel = await converter.convert(ctx, channel)
            words = [w.strip().lower() for w in words_part.split(',') if w.strip()]
        except commands.BadArgument:
            # If channel parse fails, use current channel
            channel = ctx.channel
            words = [w.strip().lower() for w in args.split(',') if w.strip()]
        
        async with self.config.guild(ctx.guild).channels() as channels:
            channel_id = str(channel.id)
            if channel_id not in channels:
                channels[channel_id] = []
            
            added = []
            for word in words:
                if word not in channels[channel_id]:
                    channels[channel_id].append(word)
                    added.append(word)
            
            embed = discord.Embed(color=0x00ff00)
            if added:
                embed.title = f"✅ Added {len(added)} Words"
                embed.description = f"To {channel.mention}'s filter"
                embed.add_field(
                    name="New Words",
                    value=', '.join(f'`{word}`' for word in added) or "None",
                    inline=False
                )
                current_words = '\n'.join(f'• `{w}`' for w in channels[channel_id]) or "None"
                embed.add_field(
                    name="Current Filter Words",
                    value=', '.join(f'`{w}`' for w in channels[channel_id]) or "None",
                    inline=False
                )
            else:
                embed.title = "⏩ No Changes"
                embed.description = "All specified words were already in the filter"
                embed.color = 0xffd700
            
            await ctx.send(embed=embed)

    @filter.command()
    @commands.admin_or_permissions(administrator=True)
    async def removeword(self, ctx, *, args: str):
        """Remove words from a channel's filter"""
        try:
            # Try to parse channel from beginning of arguments
            converter = commands.TextChannelConverter()
            channel, _, words_part = args.partition(' ')
            channel = await converter.convert(ctx, channel)
            words = [w.strip().lower() for w in words_part.split(',') if w.strip()]
        except commands.BadArgument:
            # If channel parse fails, use current channel
            channel = ctx.channel
            words = [w.strip().lower() for w in args.split(',') if w.strip()]
        
        async with self.config.guild(ctx.guild).channels() as channels:
            channel_id = str(channel.id)
            removed = []
            for word in words:
                if word in channels.get(channel_id, []):
                    channels[channel_id].remove(word)
                    removed.append(word)
            
            embed = discord.Embed(color=0x00ff00)
            if removed:
                embed.title = f"❌ Removed {len(removed)} Words"
                embed.description = f"From {channel.mention}'s filter"
                embed.add_field(
                    name="Removed Words",
                    value=', '.join(f'`{word}`' for word in removed) or "None",
                    inline=False
                )
                
                remaining = channels.get(channel_id, [])
                if remaining:
                    embed.add_field(
                        name="Remaining Words",
                        value=', '.join(f'`{w}`' for w in remaining) or "None",
                        inline=False
                    )
                else:
                    del channels[channel_id]
                    embed.add_field(
                        name="Channel Removed",
                        value="No words remaining in filter",
                        inline=False
                    )
            else:
                embed.title = "⏩ No Changes"
                embed.description = "None of these words were in the filter"
                embed.color = 0xffd700
            
            await ctx.send(embed=embed)
                
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
                word_list = ', '.join(f'`{word}`' for word in words) if words else "No words set"
                embed.add_field(
                    name=f"#{channel.name}",
                    value=f"Required words: {word_list}",
                    inline=False
                )
        
        if not embed.fields:
            embed.description = "No channels being filtered"
        
        await ctx.send(embed=embed)

    @commands.command()
    async def ilovefriendship(self, ctx):
        """Grants the Pegasister role"""
        role_id = 1350605344769839194
        role = ctx.guild.get_role(role_id)
        
        if not role:
            return await ctx.send("❌ Pegasister role not found")
            
        if role in ctx.author.roles:
            return await ctx.send("You already have the Pegasister role! 💖")
            
        try:
            await ctx.author.add_roles(role)
            await ctx.send("🌈✨ You've been granted the Pegasister role! Welcome to the club, you can never leave!")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permissions to assign roles")
            
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
            
        if message.channel.permissions_for(message.author).administrator:
            return

        prefixes = await self.bot.get_valid_prefixes(message.guild)
        content = message.content.lower().strip()
        for prefix in prefixes:
            if content.startswith(prefix.lower()):
                cmd = content[len(prefix):].strip()
                if cmd.startswith("filter list") or cmd.startswith("ilovefriendship"):
                    return
                    
        channels = await self.config.guild(message.guild).channels()        
        channel_id = str(message.channel.id)

        if channel_id in channels:
            required_words = channels[channel_id]
            if required_words:
                message_content = self.strip_markdown(message.content)
                regexes = [self.wildcard_to_regex(word) for word in required_words]
                if not any(regex.search(message_content) for regex in regexes):
                    try:
                        await message.delete()
                        await self.log_filtered_message(message)
                        
                        try:
                            word_list = ', '.join(f'`{word}`' for word in required_words)
                            await message.author.send(
                                f"Your message in {message.channel.mention} was filtered because "
                                f"it did not contain one of the following words: {word_list}",
                                delete_after=20
                            )
                        except discord.Forbidden:
                            pass

                        try:
                            await message.author.timeout(
                                timedelta(minutes=1), 
                                reason=f"Filter violation in #{message.channel.name}"
                            )
                        except discord.Forbidden:
                            pass

                    except discord.HTTPException:
                        pass
                        
    def wildcard_to_regex(self, word):
        parts = word.split('*')
        escaped = [re.escape(part) for part in parts]
        pattern = '.*'.join(escaped)
        return re.compile(pattern)
        
    def strip_markdown(self, content):
        patterns = [
            (r'```.*?```', '', re.DOTALL),                # Code blocks
            (r'`[^`]*`', '', 0),                           # Inline code
            (r'(~{2,}|\|{2,})(.*?)\1', '', re.DOTALL),     # Spoilers/strikethrough
            (r'\[([^\]]+)\]\([^\)]+\)', r'\1', 0),         # Hyperlinks
            (r'(\*\*|__|\*)(.*?)\1', r'\2', 0),            # Bold/italic/underline
            (r'\n.*?#-.*?\n', '\n', 0)                     # Special line patterns
        ]
    
        for regex_pattern, replacement, flags in patterns:
            content = re.sub(regex_pattern, replacement, content, flags=flags)
        
        content = re.sub(r'[~|*_`-]+', '', content)
        return content.lower()

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
