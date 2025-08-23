import asyncio
import logging
from datetime import time, timedelta, timezone, datetime

import discord
import pytz
from redbot.core import Config, commands, app_commands
from redbot.core.bot import Red
from discord.ext import tasks

log = logging.getLogger("red.aidenkrz-cogs.weekendlocker")

class WeekendLocker(commands.Cog):
    """
    Automatically locks channels during the weekend.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=9876543210, force_registration=True
        )
        default_guild = {
            "channels": [],
            "lock_time": "00:00",
            "unlock_time": "00:00",
            "lock_day": "saturday",
            "unlock_day": "monday",
            "timezone": "America/Chicago",
            "enabled": False,
            "locked_channels": {}, # Store lock status and original permissions
        }
        self.config.register_guild(**default_guild)
        self.weekend_lock_task.start()

    def cog_unload(self):
        self.weekend_lock_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_settings = await self.config.guild(message.guild).all()
        if not guild_settings["enabled"]:
            return
            
        locked_channels = guild_settings.get("locked_channels", {})
        if str(message.channel.id) in locked_channels:
            if not message.channel.permissions_for(message.author).manage_messages:
                try:
                    await message.delete()
                    await message.author.timeout(timedelta(minutes=10), reason="Violated channel lock.")
                except discord.Forbidden:
                    log.error(f"Failed to delete message or timeout user in {message.channel.name} ({message.guild.name}). Missing permissions.")
                except Exception as e:
                    log.error(f"An error occurred in on_message: {e}")

    async def get_next_event(self, guild_settings):
        tz = pytz.timezone(guild_settings["timezone"])
        now = datetime.now(tz)

        lock_day = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(guild_settings["lock_day"])
        unlock_day = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(guild_settings["unlock_day"])

        lock_hour, lock_minute = map(int, guild_settings["lock_time"].split(':'))
        unlock_hour, unlock_minute = map(int, guild_settings["unlock_time"].split(':'))

        next_lock_time = now.replace(hour=lock_hour, minute=lock_minute, second=0, microsecond=0)
        while next_lock_time.weekday() != lock_day or next_lock_time <= now:
            next_lock_time += timedelta(days=1)

        next_unlock_time = now.replace(hour=unlock_hour, minute=unlock_minute, second=0, microsecond=0)
        while next_unlock_time.weekday() != unlock_day or next_unlock_time <= now:
            next_unlock_time += timedelta(days=1)

        if next_lock_time < next_unlock_time:
            return "lock", next_lock_time
        else:
            return "unlock", next_unlock_time

    @tasks.loop(minutes=1)
    async def weekend_lock_task(self):
        all_guilds = await self.config.all_guilds()
        for guild_id, guild_settings in all_guilds.items():
            if not guild_settings["enabled"]:
                continue

            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            event, event_time = await self.get_next_event(guild_settings)
            tz = pytz.timezone(guild_settings["timezone"])
            now = datetime.now(tz)
            
            # Pre-lock warning
            pre_lock_warning_time = event_time - timedelta(minutes=5)
            if now.weekday() == pre_lock_warning_time.weekday() and now.hour == pre_lock_warning_time.hour and now.minute == pre_lock_warning_time.minute:
                if event == "lock":
                    for channel_id in guild_settings["channels"]:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            try:
                                await channel.send("This channel is about to lock in 5 minutes.")
                            except discord.Forbidden:
                                log.warning(f"Failed to send pre-lock warning in {channel.name} ({guild.name}).")

            # Lock/Unlock event
            if now.weekday() == event_time.weekday() and now.hour == event_time.hour and now.minute == event_time.minute:
                if event == "lock":
                    await self.lock_channels(guild, guild_settings, event_time)
                elif event == "unlock":
                    await self.unlock_channels(guild, guild_settings)

    async def lock_channels(self, guild, guild_settings, unlock_time):
        """Announces lock and marks channels as locked in config."""
        locked_channels_data = {}
        for channel_id in guild_settings["channels"]:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    unlock_timestamp = f"<t:{int(unlock_time.timestamp())}:F>"
                    await channel.send(f"This channel is locked until {unlock_timestamp}. Go outside and enjoy your weekend!")
                    locked_channels_data[str(channel_id)] = True
                except discord.Forbidden:
                    log.warning(f"Failed to send lock message in {channel.name} ({guild.name}).")
        
        await self.config.guild(guild).locked_channels.set(locked_channels_data)

    async def unlock_channels(self, guild, guild_settings):
        """Announces unlock and clears locked status from config."""
        for channel_id in guild_settings["channels"]:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send("Channel unlocked!")
                except discord.Forbidden:
                    log.warning(f"Failed to send unlock message in {channel.name} ({guild.name}).")
        
        await self.config.guild(guild).locked_channels.clear()

    async def check_and_apply_lock(self, guild: discord.Guild):
        """Checks if the current time is within the lock period and applies the correct state."""
        guild_settings = await self.config.guild(guild).all()
        if not guild_settings["enabled"]:
            return

        tz = pytz.timezone(guild_settings["timezone"])
        now = datetime.now(tz)

        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        lock_day_index = days.index(guild_settings["lock_day"])
        unlock_day_index = days.index(guild_settings["unlock_day"])

        lock_hour, lock_minute = map(int, guild_settings["lock_time"].split(':'))
        unlock_hour, unlock_minute = map(int, guild_settings["unlock_time"].split(':'))

        days_since_lock_day = (now.weekday() - lock_day_index + 7) % 7
        last_lock_date = now - timedelta(days=days_since_lock_day)
        lock_time = last_lock_date.replace(hour=lock_hour, minute=lock_minute, second=0, microsecond=0)

        days_until_unlock_day = (unlock_day_index - lock_time.weekday() + 7) % 7
        if days_until_unlock_day == 0 and lock_time.time() >= time(unlock_hour, unlock_minute):
             days_until_unlock_day = 7
        
        unlock_date = lock_time + timedelta(days=days_until_unlock_day)
        unlock_time = unlock_date.replace(hour=unlock_hour, minute=unlock_minute, second=0, microsecond=0)

        if lock_time <= now < unlock_time:
            log.info(f"[{guild.name}] Time is within lock period. Locking channels.")
            await self.lock_channels(guild, guild_settings, unlock_time)
        else:
            log.info(f"[{guild.name}] Time is outside lock period. Unlocking channels.")
            await self.unlock_channels(guild, guild_settings)


    @weekend_lock_task.before_loop
    async def before_weekend_lock_task(self):
        await self.bot.wait_until_ready()
        log.info("WeekendLocker task waiting for bot to be ready...")

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def weekendlockerset(self, ctx: commands.Context):
        """
        Settings for the Weekend Locker.
        """
        await ctx.send_help()

    @weekendlockerset.command(name="addchannel")
    async def wl_addchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Add a channel to the weekend lock list.
        """
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id not in channels:
                channels.append(channel.id)
                await ctx.send(f"{channel.mention} has been added to the lock list.")
            else:
                await ctx.send(f"{channel.mention} is already in the lock list.")
    
    @weekendlockerset.command(name="removechannel")
    async def wl_removechannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Remove a channel from the weekend lock list.
        """
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
                await ctx.send(f"{channel.mention} has been removed from the lock list.")
            else:
                await ctx.send(f"{channel.mention} is not in the lock list.")

    @weekendlockerset.command(name="settings")
    async def wl_settings(self, ctx: commands.Context):
        """
        Display the current Weekend Locker settings.
        """
        settings = await self.config.guild(ctx.guild).all()
        channels = [f"<#{cid}>" for cid in settings["channels"]]
        
        embed = discord.Embed(title="WeekendLocker Settings", color=await ctx.embed_color())
        embed.add_field(name="Status", value="Enabled" if settings["enabled"] else "Disabled", inline=False)
        embed.add_field(name="Channels", value="\n".join(channels) if channels else "None", inline=False)
        embed.add_field(name="Timezone", value=settings["timezone"], inline=False)
        embed.add_field(name="Lock Time", value=f"{settings['lock_day'].capitalize()} at {settings['lock_time']}", inline=True)
        embed.add_field(name="Unlock Time", value=f"{settings['unlock_day'].capitalize()} at {settings['unlock_time']}", inline=True)
        await ctx.send(embed=embed)
    
    @weekendlockerset.command(name="setlocktime")
    async def wl_setlocktime(self, ctx: commands.Context, day: str, time_str: str):
        """
        Set the lock day and time.
        Format: Day Time (e.g., Saturday 00:00)
        """
        if day.lower() not in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            return await ctx.send("Invalid day. Please use a full day name (e.g., Saturday).")
        try:
            time.fromisoformat(time_str)
        except ValueError:
            return await ctx.send("Invalid time format. Please use HH:MM format.")
        
        await self.config.guild(ctx.guild).lock_day.set(day.lower())
        await self.config.guild(ctx.guild).lock_time.set(time_str)
        await ctx.send(f"Lock time set to {day.capitalize()} at {time_str}.")

    @weekendlockerset.command(name="setunlocktime")
    async def wl_setunlocktime(self, ctx: commands.Context, day: str, time_str: str):
        """
        Set the unlock day and time.
        Format: Day Time (e.g., Monday 00:00)
        """
        if day.lower() not in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            return await ctx.send("Invalid day. Please use a full day name (e.g., Monday).")
        try:
            time.fromisoformat(time_str)
        except ValueError:
            return await ctx.send("Invalid time format. Please use HH:MM format.")

        await self.config.guild(ctx.guild).unlock_day.set(day.lower())
        await self.config.guild(ctx.guild).unlock_time.set(time_str)
        await ctx.send(f"Unlock time set to {day.capitalize()} at {time_str}.")


    @weekendlockerset.command(name="settimezone")
    async def wl_settimezone(self, ctx: commands.Context, tz: str):
        """
        Set the timezone for the locker.
        Example: America/New_York
        """
        if tz not in pytz.all_timezones:
            return await ctx.send("Invalid timezone. A list of valid timezones can be found at https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
        await self.config.guild(ctx.guild).timezone.set(tz)
        await ctx.send(f"Timezone set to {tz}.")

    @weekendlockerset.command(name="toggle")
    async def wl_toggle(self, ctx: commands.Context, on_off: bool):
        """
        Toggle the weekend locker on or off.
        """
        await self.config.guild(ctx.guild).enabled.set(on_off)
        if on_off:
            await ctx.send("Weekend Locker enabled.")
            # Manually check if channels should be locked right now in the background
            asyncio.create_task(self.check_and_apply_lock(ctx.guild))
        else:
            await ctx.send("Weekend Locker disabled.")
            # Manually unlock all channels if disabling
            guild_settings = await self.config.guild(ctx.guild).all()
            await self.unlock_channels(ctx.guild, guild_settings)

    @weekendlockerset.command(name="forcelock")
    async def wl_forcelock(self, ctx: commands.Context):
        """
        Manually lock all configured channels immediately.
        """
        guild_settings = await self.config.guild(ctx.guild).all()
        unlock_time = datetime.now(pytz.timezone(guild_settings["timezone"])) + timedelta(hours=24)
        await self.lock_channels(ctx.guild, guild_settings, unlock_time)
        await ctx.send("All configured channels have been manually locked.")

    @weekendlockerset.command(name="forceunlock")
    async def wl_forceunlock(self, ctx: commands.Context):
        """
        Manually unlock all configured channels immediately.
        """
        guild_settings = await self.config.guild(ctx.guild).all()
        await self.unlock_channels(ctx.guild, guild_settings)
        await ctx.send("All configured channels have been manually unlocked.")

    @weekendlockerset.command(name="getnow")
    async def wl_getnow(self, ctx: commands.Context):
        """
        Shows the current time the bot is using.
        """
        guild_settings = await self.config.guild(ctx.guild).all()
        tz = pytz.timezone(guild_settings["timezone"])
        now = datetime.now(tz)
        await ctx.send(f"The current time is: {now.strftime('%A, %Y-%m-%d %H:%M:%S %Z%z')}")