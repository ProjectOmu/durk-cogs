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
            "query": '{level="error"}',
            "last_timestamp": None,
            "enabled": False,
        }
        self.config.register_guild(**default_guild)
        
        self.interactive_logs = {}
        self.number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        self.loki_task.start()

    def cog_unload(self):
        self.loki_task.cancel()

    @tasks.loop(seconds=30)
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

        raw_log_entries = []
        for stream in data["data"]["result"]:
            for value_pair in stream["values"]:
                raw_log_entries.append(
                    {"timestamp": value_pair[0], "message": value_pair[1], "stream": stream.get("stream", {})}
                )
        raw_log_entries.sort(key=lambda x: int(x["timestamp"]))

        if not raw_log_entries:
            log.info(f"[{guild.id}] No new log entries after parsing.")
            return

        log.info(f"[{guild.id}] Found {len(raw_log_entries)} new log entries.")

        new_latest_timestamp_ns_str = raw_log_entries[-1]["timestamp"]

        ping_content = ""
        if settings.get("role_id"):
            role = guild.get_role(settings["role_id"])
            if role:
                ping_content = f"{role.mention} "
            else:
                log.warning(f"[{guild.id}] Configured role ID {settings['role_id']} not found.")

        num_logs = len(raw_log_entries)
        first_log_ts_ns = raw_log_entries[0]["timestamp"]
        last_log_ts_ns = new_latest_timestamp_ns_str

        first_log_ts_seconds = int(first_log_ts_ns) // 1_000_000_000
        last_log_ts_seconds = int(last_log_ts_ns) // 1_000_000_000

        embed_title = "Loki Log Summary"
        embed_description = (
            f"Found **{num_logs}** new log entr{'ies' if num_logs > 1 else 'y'} "
            f"between <t:{first_log_ts_seconds}:T> and <t:{last_log_ts_seconds}:T>.\n"
            f"React with an emoji to view full details for the corresponding log."
        )
        embed_color = guild.me.color if guild.me else discord.Color.blue()

        embed = discord.Embed(title=embed_title, description=embed_description, color=embed_color)

        logs_for_interaction = raw_log_entries[:len(self.number_emojis)]

        for i, entry in enumerate(logs_for_interaction):
            server_label = entry['stream'].get('Server', entry['stream'].get('instance', 'Unknown Source'))
            
            first_line = entry['message'].split('\n', 1)[0]
            max_field_value_len = 1000
            if len(first_line) > max_field_value_len - 10:
                first_line = first_line[:max_field_value_len - 13] + "..."

            field_name = f"{self.number_emojis[i]} Log from `{server_label}`"
            field_value = f"```{first_line}```"
            embed.add_field(name=field_name, value=field_value, inline=False)
        
        if num_logs > len(logs_for_interaction):
            embed.set_footer(text=f"Showing first {len(logs_for_interaction)} of {num_logs} logs. Full details via reactions.")
        else:
            embed.set_footer(text="Full details available via reactions for 1 hour.")

        try:
            summary_message = await channel.send(content=ping_content if ping_content else None, embed=embed)
        except discord.HTTPException as e:
            log.error(f"[{guild.id}] Discord API error sending summary log embed: {e}")
            return

        logs_for_interaction = raw_log_entries[:len(self.number_emojis)]
        self.interactive_logs[summary_message.id] = logs_for_interaction
        
        for i in range(min(num_logs, len(self.number_emojis))):
            try:
                await summary_message.add_reaction(self.number_emojis[i])
            except discord.HTTPException:
                log.warning(f"[{guild.id}] Failed to add reaction {self.number_emojis[i]} to summary message.")
                break

        asyncio.create_task(self._cleanup_interactive_log(summary_message.id, delay=3600))

        if new_latest_timestamp_ns_str != last_timestamp_ns_str and new_latest_timestamp_ns_str is not None:
            await self.config.guild(guild).last_timestamp.set(new_latest_timestamp_ns_str)
            log.info(f"[{guild.id}] Updated last_timestamp to {new_latest_timestamp_ns_str}")

    async def _cleanup_interactive_log(self, message_id: int, delay: int):
        """Removes an interactive log entry after a delay."""
        await asyncio.sleep(delay)
        if message_id in self.interactive_logs:
            del self.interactive_logs[message_id]
            log.debug(f"Cleaned up interactive log for message ID: {message_id}")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Handles reactions on summary messages to display specific logs."""
        if user.bot:
            return

        message = reaction.message
        if message.id not in self.interactive_logs:
            return

        try:
            emoji_index = self.number_emojis.index(str(reaction.emoji))
        except ValueError:
            return

        if not message.guild or not message.channel:
            log.warning(f"Could not process reaction for message {message.id}, guild or channel not found.")
            return
            
        guild_id = message.guild.id
        
        log_batch = self.interactive_logs.get(message.id)
        if not log_batch or emoji_index >= len(log_batch):
            log.warning(f"[{guild_id}] Invalid reaction index {emoji_index} for message {message.id}")
            return

        entry_to_display = log_batch[emoji_index]
        
        ts_ns = entry_to_display["timestamp"]
        msg_text = entry_to_display["message"]
        stream_labels = entry_to_display["stream"]
        label_str = ", ".join([f"`{k}`=`{v}`" for k, v in stream_labels.items()])
        
        max_log_line_len = 1800 - len(label_str)
        if len(msg_text) > max_log_line_len:
            msg_text = msg_text[:max_log_line_len] + "... (truncated)"

        ts_seconds = int(ts_ns) // 1_000_000_000
        discord_timestamp = f"<t:{ts_seconds}:F> (<t:{ts_seconds}:R>)"

        settings = await self.config.guild(message.guild).all()
        ping_content = ""
        if settings.get("role_id"):
            role = message.guild.get_role(settings["role_id"])
            if role:
                pass

        formatted_message = (
            f"{ping_content}**Log Detail ({emoji_index + 1}/{len(log_batch)}):** [{label_str}]\n"
            f"```\n{msg_text}\n```\n"
            f"Timestamp: {discord_timestamp}"
        )

        try:
            await message.channel.send(formatted_message)
        except discord.HTTPException as e:
            log.error(f"[{guild_id}] Discord API error sending detailed log: {e}")
            try:
                await message.channel.send(f"Error displaying log detail: {e}")
            except discord.HTTPException:
                pass

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

        Default: `{level="error"}`
        Example: [p]lokiset query {App="Robust.Server", level="error"} |= "timeout"
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