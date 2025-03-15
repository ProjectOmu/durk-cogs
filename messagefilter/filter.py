from redbot.core import commands, Config, checks
import discord

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
    async def addword(self, ctx, channel: discord.TextChannel, *words):
        """Add required words for a channel"""
        if not words:
            return await ctx.send("Please provide words to add")
        
        async with self.config.guild(ctx.guild).channels() as channels:
            if str(channel.id) not in channels:
                channels[str(channel.id)] = []
            
            added = []
            for word in words:
                if word.lower() not in channels[str(channel.id)]:
                    channels[str(channel.id)].append(word.lower())
                    added.append(word)
            
            if added:
                await ctx.send(f"Added words: {', '.join(added)}")
            else:
                await ctx.send("No new words were added")

    @filter.command()
    async def list(self, ctx):
        """Show currently filtered channels and their required words"""
        channels = await self.config.guild(ctx.guild).channels()
        embed = discord.Embed(title="Filtered Channels", color=0x00ff00)
        
        for channel_id, words in channels.items():
            channel = ctx.guild.get_channel(int(channel_id))
            if channel:
                word_list = ', '.join(words) if words else "No words set"
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
        if message.author.bot:
            return
        
        if not message.guild:
            return
        
        channels = await self.config.guild(message.guild).channels()
        channel_id = str(message.channel.id)
        
        if channel_id in channels:
            required_words = channels[channel_id]
            if required_words:
                message_words = message.content.lower().split()
                if not any(word in message_words for word in required_words):
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
