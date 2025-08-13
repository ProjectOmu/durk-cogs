import asyncio
import logging
from typing import Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red
from mastodon import Mastodon
from bs4 import BeautifulSoup

log = logging.getLogger("red.durk-cogs.mastodonfeeder")

class MastodonFeeder(commands.Cog):
    """
    Automatically posts embeds of all mastodon posts from an instance to a channel.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567891, force_registration=True
        )
        default_guild = {
            "instance_url": None,
            "channel_id": None,
            "last_post_id": None,
            "enabled": False,
        }
        self.config.register_guild(**default_guild)

        self.mastodon_task.start()

    def cog_unload(self):
        self.mastodon_task.cancel()

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def mastodonset(self, ctx: commands.Context):
        """
        Settings for the Mastodon Feeder.
        """
        await ctx.send_help()

    @mastodonset.command(name="instance")
    async def mastodonset_instance(self, ctx: commands.Context, instance_url: str):
        """
        Set the Mastodon instance URL.
        """
        await self.config.guild(ctx.guild).instance_url.set(instance_url)
        await ctx.send(f"Mastodon instance URL set to: `{instance_url}`")

    @mastodonset.command(name="channel")
    async def mastodonset_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Set the channel to post Mastodon updates to.
        """
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Mastodon update channel set to: {channel.mention}")

    @mastodonset.command(name="toggle")
    async def mastodonset_toggle(self, ctx: commands.Context, on_off: Optional[bool] = None):
        """
        Toggle the Mastodon feeder on or off.
        """
        current_status = await self.config.guild(ctx.guild).enabled()
        if on_off is None:
            await ctx.send(f"Mastodon feeder is currently {'enabled' if current_status else 'disabled'}.")
            return

        await self.config.guild(ctx.guild).enabled.set(on_off)
        if on_off:
            await ctx.send("Mastodon feeder enabled.")
        else:
            await ctx.send("Mastodon feeder disabled.")

    async def _fetch_and_post_statuses(self, guild: discord.Guild, channel: discord.TextChannel, settings: dict):
        instance_url = settings["instance_url"]
        last_post_id = settings.get("last_post_id")

        try:
            mastodon = Mastodon(api_base_url=instance_url)
            timeline = mastodon.timeline_public(since_id=last_post_id, limit=40, local=True)
        except Exception as e:
            log.error(f"[{guild.id}] Error connecting to Mastodon instance: {e}")
            return

        if not timeline:
            return

        new_latest_post_id = timeline[0]["id"]

        for post in reversed(timeline):
            soup = BeautifulSoup(post['content'], 'html.parser')
            content = soup.get_text()
            if len(content) > 1024:
                content = content[:1021] + "..."

            embed = discord.Embed(
                description=content,
                url=post['url'],
                timestamp=post['created_at'],
                color=await self.bot.get_embed_color(channel)
            )

            embed.set_author(name=f"{post['account']['display_name']} (@{post['account']['acct']})", url=post['account']['url'], icon_url=post['account']['avatar'])
            
            if post['media_attachments']:
                embed.set_image(url=post['media_attachments'][0]['url'])

            embed.set_footer(text="Mastodon", icon_url="https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/Mastodon_Logotype_%28Simple%29.svg/2048px-Mastodon_Logotype_%28Simple%29.svg.png")

            await channel.send(embed=embed)

        await self.config.guild(guild).last_post_id.set(new_latest_post_id)

    @tasks.loop(minutes=5)
    async def mastodon_task(self):
        all_guilds = await self.config.all_guilds()
        for guild_id, settings in all_guilds.items():
            if not settings["enabled"] or not settings["instance_url"] or not settings["channel_id"]:
                continue

            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            channel = guild.get_channel(settings["channel_id"])
            if not channel:
                log.warning(f"Channel {settings['channel_id']} not found in guild {guild_id}")
                continue
            
            await self._fetch_and_post_statuses(guild, channel, settings)

    @mastodon_task.before_loop
    async def before_mastodon_task(self):
        await self.bot.wait_until_ready()
        log.info("MastodonFeeder task waiting for bot to be ready...")

    @mastodonset.command(name="settings")
    async def mastodonset_settings(self, ctx: commands.Context):
        """
        Display the current Mastodon feeder settings.
        """
        settings = await self.config.guild(ctx.guild).all()
        instance_url = settings.get("instance_url", "Not set")
        channel_id = settings.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "Not set"
        enabled = "Enabled" if settings.get("enabled") else "Disabled"
        last_post_id = settings.get("last_post_id", "N/A")

        embed = discord.Embed(title="MastodonFeeder Settings", color=await ctx.embed_color())
        embed.add_field(name="Status", value=enabled, inline=False)
        embed.add_field(name="Mastodon Instance", value=f"`{instance_url}`", inline=False)
        embed.add_field(name="Post Channel", value=channel_mention, inline=False)
        embed.add_field(name="Last Post ID Processed", value=f"`{last_post_id}`", inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    @commands.is_owner()
    async def testmastodon(self, ctx: commands.Context):
        """
        Manually trigger the Mastodon feeder to test it.
        """
        settings = await self.config.guild(ctx.guild).all()
        if not settings["enabled"]:
            await ctx.send("MastodonFeeder is not enabled for this server. Use `[p]mastodonset toggle true`.")
            return
        if not settings["instance_url"]:
            await ctx.send("Mastodon instance URL is not set. Use `[p]mastodonset instance <your_instance_url>`.")
            return
        if not settings["channel_id"]:
            await ctx.send("Post channel is not set. Use `[p]mastodonset channel <#channel>`.")
            return

        channel = ctx.guild.get_channel(settings["channel_id"])
        if not channel:
            await ctx.send(f"Configured post channel (ID: {settings['channel_id']}) not found.")
            return

        await ctx.send(f"Manually fetching posts for {ctx.guild.name}...")
        try:
            await self._fetch_and_post_statuses(ctx.guild, channel, settings)
            await ctx.send("Manual fetch attempt complete. Check the post channel.")
        except Exception as e:
            await ctx.send(f"An error occurred during manual fetch: ```{e}```")
            log.exception(f"Error during manual mastodon fetch for guild {ctx.guild.id}", exc_info=e)
