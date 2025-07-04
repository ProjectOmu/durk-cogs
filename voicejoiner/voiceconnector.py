import discord
from redbot.core import commands

class VoiceConnector(commands.Cog):
    """
    A simple cog to connect the bot to a specified voice channel.
    """

    def __init__(self, bot):
        self.bot = bot

    async def cog_unload(self):
        """Cog unload cleanup. Disconnects from any voice channels."""
        for guild in self.bot.guilds:
            if guild.voice_client:
                await guild.voice_client.disconnect(force=True)

    @commands.command()
    @commands.guild_only()
    @commands.mod_or_permissions(manage_channels=True)
    async def vcjoin(self, ctx: commands.Context, *, channel: discord.VoiceChannel):
        """
        Makes the bot join a specific voice channel.

        You must provide the name or ID of the voice channel.
        """
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
            await ctx.send(f"Moved to **{channel.name}**.")
        else:
            try:
                await channel.connect()
                await ctx.send(f"Connected to **{channel.name}**.")
            except discord.Forbidden:
                await ctx.send("I don't have permission to join that voice channel.")
            except Exception as e:
                await ctx.send(f"An error occurred: {e}")

    @commands.command()
    @commands.guild_only()
    @commands.mod_or_permissions(manage_channels=True)
    async def vcleave(self, ctx: commands.Context):
        """
        Makes the bot leave its current voice channel.
        """
        if ctx.voice_client is None:
            return await ctx.send("I'm not connected to a voice channel.")

        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel.")
