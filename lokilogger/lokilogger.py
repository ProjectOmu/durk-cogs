import asyncio
import logging
from typing import Optional

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.yourcog.lokilogger")


class LokiLogger(commands.Cog):
    """
    Fetches Loki logs and posts them to a channel.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567890, force_registration=True
        )
        default_guild = {
            "loki_url": None,
            "channel_id": None,
            "role_id": None,
            "query": '{stream="error"}',
            "last_timestamp": None,
            "enabled": False,
        }
        self.config.register_guild(**default_guild)
        self.loki_task.start()

    def cog_unload(self):
        self.loki_task.cancel()

    @tasks.loop(minutes=5)
    async def loki_task(self):
        all_guilds = await self.config.all_guilds()
        for guild_id, settings in all_guilds.items():
            if not settings["enabled"] or not settings["loki_url"] or not settings["channel_id"]:
                continue

            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            channel = guild.get_channel(settings["channel_id"])
            if not channel:
                log.warning(f"Channel {settings['channel_id']} not found in guild {guild_id}")
                continue

            await self._fetch_and_post_logs(guild, channel, settings)

    async def _fetch_and_post_logs(self, guild, channel, settings):
        loki_url = settings["loki_url"]
        query = settings["query"]
        last_timestamp_ns_str = settings.get("last_timestamp")

        import time
        end_ts_ns = int(time.time() * 1_000_000_000)

        if last_timestamp_ns_str:
            start_ts_ns = int(last_timestamp_ns_str)
        else:
            start_ts_ns = end_ts_ns - (5 * 60 * 1_000_000_000)

        max_initial_fetch_duration_ns = 1 * 60 * 60 * 1_000_000_000
        if not last_timestamp_ns_str and (end_ts_ns - start_ts_ns > max_initial_fetch_duration_ns):
            start_ts_ns = end_ts_ns - max_initial_fetch_duration_ns
            log.info(f"[{guild.id}] No last timestamp, capping initial fetch to 1 hour ago.")

        params = {
            "query": query,
            "start": str(start_ts_ns + 1),
            "end": str(end_ts_ns),
            "limit": 50,
            "direction": "forward",
        }

        log.info(
            f"[{guild.id}] Fetching logs from Loki: URL='{loki_url}', Query='{query}', "
            f"Start='{params['start']}', End='{params['end']}'"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(loki_url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
        except aiohttp.ClientError as e:
            log.error(f"[{guild.id}] Error connecting to Loki API: {e}")
            await channel.send(f"Error connecting to Loki: `{e}`. Please check the URL and Loki server status.")
            return
        except Exception as e:
            log.error(f"[{guild.id}] Error querying Loki or parsing response: {e}")
            await channel.send(f"Error querying Loki: `{e}`.")
            return

        if not data or "data" not in data or "result" not in data["data"]:
            log.info(f"[{guild.id}] No new logs found or unexpected response structure from Loki.")
            return

        log_entries = []
        for stream in data["data"]["result"]:
            for value_pair in stream["values"]:
                log_entries.append(
                    {"timestamp": value_pair[0], "message": value_pair[1], "stream": stream.get("stream", {})}
                )
        log_entries.sort(key=lambda x: int(x["timestamp"]))

        if not log_entries:
            log.info(f"[{guild.id}] No new log entries after parsing.")
            return

        log.info(f"[{guild.id}] Found {len(log_entries)} new log entries.")

        new_latest_timestamp_ns_str = last_timestamp_ns_str
        ping_content = ""
        if settings.get("role_id"):
            role = guild.get_role(settings["role_id"])
            if role:
                ping_content = f"{role.mention} "
            else:
                log.warning(f"[{guild.id}] Configured role ID {settings['role_id']} not found.")


        for entry in log_entries:
            ts_ns = entry["timestamp"]
            msg = entry["message"]
            stream_labels = entry["stream"]
            label_str = ", ".join([f"`{k}`=`{v}`" for k, v in stream_labels.items()])
            
            max_log_line_len = 1900 - len(label_str)
            if len(msg) > max_log_line_len:
                msg = msg[:max_log_line_len] + "... (truncated)"

            formatted_message = f"{ping_content}**Loki Log:** [{label_str}]\n```\n{msg}\n```\nTimestamp: `{ts_ns}`"
            ping_content = ""

            try:
                await channel.send(formatted_message)
            except discord.HTTPException as e:
                log.error(f"[{guild.id}] Discord API error sending log: {e}")
                await channel.send(f"Error sending log to Discord: `{e}`. The log might be too long or malformed.")
                break
            
            if new_latest_timestamp_ns_str is None or int(ts_ns) > int(new_latest_timestamp_ns_str):
                new_latest_timestamp_ns_str = ts_ns
            
            await asyncio.sleep(1)

        if new_latest_timestamp_ns_str != last_timestamp_ns_str and new_latest_timestamp_ns_str is not None:
            await self.config.guild(guild).last_timestamp.set(new_latest_timestamp_ns_str)
            log.info(f"[{guild.id}] Updated last_timestamp to {new_latest_timestamp_ns_str}")

    @loki_task.before_loop
    async def before_loki_task(self):
        await self.bot.wait_until_ready()
        log.info("LokiLogger task waiting for bot to be ready...")

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def lokiset(self, ctx: commands.Context):
        """
        Configure LokiLogger settings.
        """
        await ctx.send_help()

    @lokiset.command(name="url")
    async def lokiset_url(self, ctx: commands.Context, url: str):
        """
        Set the Loki API URL.

        Example: [p]lokiset url http://localhost:3100/loki/api/v1/query_range
        """
        if not url.endswith("/loki/api/v1/query_range") and not url.endswith("/loki/api/v1/query"):
            await ctx.send(
                "The URL should typically end with `/loki/api/v1/query_range` or `/loki/api/v1/query`."
            )
        await self.config.guild(ctx.guild).loki_url.set(url)
        await ctx.send(f"Loki API URL set to: `{url}`")

    @lokiset.command(name="channel")
    async def lokiset_channel(self, ctx: commands.Context, channel: commands.TextChannelConverter):
        """
        Set the channel where logs will be posted.
        """
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Log channel set to: {channel.mention}")

    @lokiset.command(name="role")
    async def lokiset_role(self, ctx: commands.Context, role: commands.RoleConverter = None):
        """
        Set the role to ping when new logs are found.
        Provide no role to disable pings.
        """
        if role:
            await self.config.guild(ctx.guild).role_id.set(role.id)
            await ctx.send(f"Role to ping set to: {role.name}")
        else:
            await self.config.guild(ctx.guild).role_id.set(None)
            await ctx.send("Role pinging disabled.")

    @lokiset.command(name="query")
    async def lokiset_query(self, ctx: commands.Context, *, query: str):
        """
        Set the Loki query to fetch logs.

        Default: `{stream="error"}`
        Example: [p]lokiset query {namespace="prod", level="error"} |= "timeout"
        """
        await self.config.guild(ctx.guild).query.set(query)
        await ctx.send(f"Loki query set to: `{query}`")

    @lokiset.command(name="toggle")
    async def lokiset_toggle(self, ctx: commands.Context, on_off: Optional[bool] = None):
        """
        Enable or disable log fetching for this server.
        If no argument is provided, the current status will be shown.
        """
        current_status = await self.config.guild(ctx.guild).enabled()
        if on_off is None:
            await ctx.send(f"Log fetching is currently {'enabled' if current_status else 'disabled'}.")
            return

        await self.config.guild(ctx.guild).enabled.set(on_off)
        if on_off:
            await ctx.send("Log fetching enabled.")
            await self.config.guild(ctx.guild).last_timestamp.set(None)
        else:
            await ctx.send("Log fetching disabled.")

    @lokiset.command(name="settings")
    async def lokiset_settings(self, ctx: commands.Context):
        """
        Show the current LokiLogger settings for this server.
        """
        settings = await self.config.guild(ctx.guild).all()
        url = settings.get("loki_url", "Not set")
        channel_id = settings.get("channel_id")
        channel_mention = f"<#{channel_id}>" if channel_id else "Not set"
        role_id = settings.get("role_id")
        role_mention = f"<@&{role_id}>" if role_id else "Not set (no pings)"
        query = settings.get("query", "Not set")
        enabled = "Enabled" if settings.get("enabled") else "Disabled"
        last_ts = settings.get("last_timestamp", "N/A")

        embed = discord.Embed(title="LokiLogger Settings", color=await ctx.embed_color())
        embed.add_field(name="Status", value=enabled, inline=False)
        embed.add_field(name="Loki URL", value=f"`{url}`", inline=False)
        embed.add_field(name="Log Channel", value=channel_mention, inline=False)
        embed.add_field(name="Ping Role", value=role_mention, inline=False)
        embed.add_field(name="Loki Query", value=f"`{query}`", inline=False)
        embed.add_field(name="Last Timestamp Processed", value=f"`{last_ts}`", inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    @commands.is_owner()
    async def testloki(self, ctx: commands.Context):
        """
        Manually trigger a Loki log fetch and post for testing.
        """
        settings = await self.config.guild(ctx.guild).all()
        if not settings["enabled"]:
            await ctx.send("LokiLogger is not enabled for this server. Use `[p]lokiset toggle true`.")
            return
        if not settings["loki_url"]:
            await ctx.send("Loki URL is not set. Use `[p]lokiset url <your_loki_url>`.")
            return
        if not settings["channel_id"]:
            await ctx.send("Log channel is not set. Use `[p]lokiset channel <#channel>`.")
            return

        channel = ctx.guild.get_channel(settings["channel_id"])
        if not channel:
            await ctx.send(f"Configured log channel (ID: {settings['channel_id']}) not found.")
            return

        await ctx.send(f"Manually fetching logs for {ctx.guild.name}...")
        try:
            await self._fetch_and_post_logs(ctx.guild, channel, settings)
            await ctx.send("Log fetch attempt complete. Check the log channel.")
        except Exception as e:
            await ctx.send(f"An error occurred during manual fetch: ```{e}```")
            log.exception(f"Error during manual loki fetch for guild {ctx.guild.id}", exc_info=e)

async def setup(bot: Red):
    cog = LokiLogger(bot)
    await bot.add_cog(cog)