import discord
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

from redbot.core import commands, Config, app_commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from discord.ui import Modal, TextInput, View, Button
from discord import Interaction, TextStyle, ButtonStyle, SelectOption, ui

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

log = logging.getLogger("red.DurkCogs.SMSNotifier")

DEFAULT_GUILD = {
    "configurations": []  
}

def mask_string(s: str, visible_chars: int = 4, mask_char: str = "X") -> str:
    """Masks a string, showing only the last `visible_chars`."""
    if not s or len(s) <= visible_chars:
        return s
    return mask_char * (len(s) - visible_chars) + s[-visible_chars:]

def mask_phone_number(phone: str) -> str:
    """Masks a phone number, e.g., +1XXX567890"""
    if not phone or len(phone) < 7: 
        return phone
    prefix = ""
    if phone.startswith("+"):
        prefix = phone[0:2] 
        rest = phone[2:]
    else:
        rest = phone
    
    if len(rest) <= 4:
        return prefix + mask_string(rest, 0) 
    
    return prefix + mask_string(rest[:-4], 0) + rest[-4:]

class SMSNotifier(commands.Cog):
    """
    Sends SMS notifications for messages in specified channels via Twilio.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier="SMSNotifierDurkCog", force_registration=True
        )
        self.config.register_guild(**DEFAULT_GUILD)

        if not TWILIO_AVAILABLE:
            log.error(
                "Twilio library not found. Please install it with `pip install twilio` "
                "for this cog to function."
            )
            

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Check if Twilio is available before running commands."""
        if not TWILIO_AVAILABLE:
            await ctx.send(
                "The Twilio library is not installed. This cog cannot function without it. "
                "Please ask the bot owner to install it using `pip install twilio`."
            )
            return False
        return True

    async def _get_guild_configs(self, guild_id: int) -> List[Dict[str, Any]]:
        return await self.config.guild_from_id(guild_id).configurations()

    async def _save_guild_configs(self, guild_id: int, configs: List[Dict[str, Any]]):
        await self.config.guild_from_id(guild_id).configurations.set(configs)

    
    class SmsConfigModal(Modal):
        def __init__(self, cog_instance: 'SMSNotifier', guild_id: int, existing_config: Optional[Dict[str, Any]] = None):
            super().__init__(title="SMS Notification Configuration" if not existing_config else "Edit SMS Notification")
            self.cog = cog_instance
            self.guild_id = guild_id
            self.existing_config_id = existing_config["config_id"] if existing_config else None

            self.channel = TextInput(
                label="Discord Channel ID or Name",
                style=TextStyle.short,
                placeholder="e.g., general or 123456789012345678",
                default=str(existing_config.get("channel_id")) if existing_config and existing_config.get("channel_id") else None,
                required=True,
            )
            self.add_item(self.channel)

            self.recipient_phone_number = TextInput(
                label="Recipient Phone Number (E.164 format)",
                style=TextStyle.short,
                placeholder="e.g., +1234567890",
                default=existing_config.get("recipient_phone_number") if existing_config else None,
                required=True,
            )
            self.add_item(self.recipient_phone_number)

            self.twilio_account_sid = TextInput(
                label="Twilio Account SID",
                style=TextStyle.short,
                placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                default=existing_config.get("twilio_account_sid") if existing_config else None,
                required=True,
            )
            self.add_item(self.twilio_account_sid)

            self.twilio_auth_token = TextInput(
                label="Twilio Auth Token",
                style=TextStyle.short, 
                placeholder="Your Twilio Auth Token",
                default=existing_config.get("twilio_auth_token") if existing_config else None,
                required=True,
            )
            self.add_item(self.twilio_auth_token)

            self.twilio_phone_number = TextInput(
                label="Twilio Sending Phone Number (E.164)",
                style=TextStyle.short,
                placeholder="Your Twilio phone number, e.g., +12223334444",
                default=existing_config.get("twilio_phone_number") if existing_config else None,
                required=True,
            )
            self.add_item(self.twilio_phone_number)

        async def on_submit(self, interaction: Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)

            guild = self.cog.bot.get_guild(self.guild_id)
            if not guild:
                await interaction.followup.send("Error: Guild not found.", ephemeral=True)
                return
            
            channel_input = self.channel.value.strip()
            try:
                target_channel_id = int(channel_input)
                target_channel = guild.get_channel_or_thread(target_channel_id)
            except ValueError:
                
                target_channel = discord.utils.get(guild.text_channels, name=channel_input)
            
            if not target_channel or not isinstance(target_channel, discord.TextChannel):
                await interaction.followup.send(
                    f"Error: Could not find a valid text channel with ID/name '{channel_input}'. "
                    "Please provide a valid text channel ID or name.",
                    ephemeral=True
                )
                return

            
            recipient_phone = self.recipient_phone_number.value.strip()
            twilio_sender_phone = self.twilio_phone_number.value.strip()
            if not (recipient_phone.startswith("+") and recipient_phone[1:].isdigit()) or \
               not (twilio_sender_phone.startswith("+") and twilio_sender_phone[1:].isdigit()):
                await interaction.followup.send(
                    "Error: Phone numbers must be in E.164 format (e.g., +1234567890).",
                    ephemeral=True
                )
                return

            new_config_entry = {
                "config_id": self.existing_config_id or str(uuid.uuid4()),
                "name": f"Rule for #{target_channel.name}",
                "channel_id": target_channel.id,
                "recipient_phone_number": recipient_phone,
                "twilio_account_sid": self.twilio_account_sid.value.strip(),
                "twilio_auth_token": self.twilio_auth_token.value.strip(), 
                "twilio_phone_number": twilio_sender_phone,
                "is_enabled": True if not self.existing_config_id else ( 
                    next((c["is_enabled"] for c in await self.cog._get_guild_configs(self.guild_id) if c["config_id"] == self.existing_config_id), True)
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": interaction.user.id,
            }

            configs = await self.cog._get_guild_configs(self.guild_id)
            if self.existing_config_id: 
                configs = [c for c in configs if c["config_id"] != self.existing_config_id]
            configs.append(new_config_entry)
            await self.cog._save_guild_configs(self.guild_id, configs)

            action = "updated" if self.existing_config_id else "added"
            await interaction.followup.send(
                f"SMS notification configuration '{new_config_entry['name']}' has been {action} for channel {target_channel.mention}.",
                ephemeral=True
            )

    
    smsnotifier_group = app_commands.Group(
        name="smsnotifier",
        description="Manage SMS notifications for this server.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True)
    )

    @smsnotifier_group.command(name="add")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def smsnotifier_add(self, interaction: Interaction):
        """Add a new SMS notification rule."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not TWILIO_AVAILABLE:
            await interaction.response.send_message(
                "Twilio library is not installed. This cog cannot function. Please contact the bot owner.",
                ephemeral=True
            )
            return
        modal = self.SmsConfigModal(self, interaction.guild_id)
        await interaction.response.send_modal(modal)

    async def config_id_autocomplete(self, interaction: Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        configs = await self._get_guild_configs(interaction.guild_id)
        choices = []
        for config_entry in configs:
            name = config_entry.get("name", "Unnamed Rule")
            config_id = config_entry.get("config_id", "")
            display_name = f"{name} ({config_id[:8]}...)"
            if current.lower() in display_name.lower() or current.lower() in config_id.lower():
                choices.append(app_commands.Choice(name=display_name, value=config_id))
        return choices[:25] 

    @smsnotifier_group.command(name="list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def smsnotifier_list(self, interaction: Interaction):
        """List all SMS notification rules for this server."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        
        configs = await self._get_guild_configs(interaction.guild_id)
        if not configs:
            await interaction.response.send_message("No SMS notification rules configured for this server.", ephemeral=True)
            return

        embed = discord.Embed(title="SMS Notification Rules", color=await self.bot.get_embed_color(interaction.channel))
        
        for conf_idx, conf in enumerate(configs):
            channel = interaction.guild.get_channel_or_thread(conf.get("channel_id", 0))
            channel_mention = channel.mention if channel else f"ID: {conf.get('channel_id', 'N/A')}"
            status = "Enabled" if conf.get("is_enabled", False) else "Disabled"
            recipient_phone_masked = mask_phone_number(conf.get("recipient_phone_number", "N/A"))
            
            field_name = f"{conf.get('name', f'Rule ID: {conf.get('config_id', 'N/A')[:8]}')} (ID: `{conf.get('config_id', 'N/A')[:8]}`)"
            field_value = (
                f"Channel: {channel_mention}\n"
                f"Recipient: {recipient_phone_masked}\n"
                f"Status: {status}"
            )
            embed.add_field(name=field_name, value=field_value, inline=False)
            if (conf_idx + 1) % 25 == 0 and conf_idx + 1 < len(configs): 
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                embed = discord.Embed(title="SMS Notification Rules (Cont.)", color=await self.bot.get_embed_color(interaction.channel))
        
        if embed.fields: 
             if not interaction.response.is_done():
                 await interaction.response.send_message(embed=embed, ephemeral=True)
             else:
                 await interaction.followup.send(embed=embed, ephemeral=True)
        elif not interaction.response.is_done(): 
            await interaction.response.send_message("No SMS notification rules to display.", ephemeral=True)


    @smsnotifier_group.command(name="remove")
    @app_commands.describe(config_id="The ID of the rule to remove.")
    @app_commands.autocomplete(config_id=config_id_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def smsnotifier_remove(self, interaction: Interaction, config_id: str):
        """Remove an SMS notification rule by its ID."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        configs = await self._get_guild_configs(interaction.guild_id)
        initial_len = len(configs)
        configs_to_keep = [c for c in configs if c.get("config_id") != config_id]

        if len(configs_to_keep) == initial_len:
            await interaction.response.send_message(f"Error: No configuration found with ID `{config_id}`.", ephemeral=True)
            return

        await self._save_guild_configs(interaction.guild_id, configs_to_keep)
        await interaction.response.send_message(f"Successfully removed SMS notification rule with ID: `{config_id}`.", ephemeral=True)

    @smsnotifier_group.command(name="toggle")
    @app_commands.describe(config_id="The ID of the rule to enable/disable.")
    @app_commands.autocomplete(config_id=config_id_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def smsnotifier_toggle(self, interaction: Interaction, config_id: str):
        """Enable or disable an SMS notification rule by its ID."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        configs = await self._get_guild_configs(interaction.guild_id)
        updated = False
        new_status_str = "unknown"
        config_name = "Unknown Rule"

        for conf in configs:
            if conf.get("config_id") == config_id:
                conf["is_enabled"] = not conf.get("is_enabled", False)
                new_status_str = "enabled" if conf["is_enabled"] else "disabled"
                updated = True
                break
        
        if not updated:
            await interaction.response.send_message(f"Error: No configuration found with ID `{config_id}`.", ephemeral=True)
            return

        await self._save_guild_configs(interaction.guild_id, configs)
        config_display_name = next((c.get("name", f"Rule ID: {config_id[:8]}") for c in configs if c.get("config_id") == config_id), f"Rule ID: {config_id[:8]}")
        await interaction.response.send_message(
            f"SMS notification rule '{config_display_name}' (ID: `{config_id}`) has been {new_status_str}.",
            ephemeral=True
        )

    @smsnotifier_group.command(name="view")
    @app_commands.describe(config_id="The ID of the rule to view.")
    @app_commands.autocomplete(config_id=config_id_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def smsnotifier_view(self, interaction: Interaction, config_id: str):
        """View details of a specific SMS notification rule."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

        configs = await self._get_guild_configs(interaction.guild_id)
        config_to_view = next((c for c in configs if c.get("config_id") == config_id), None)

        if not config_to_view:
            await interaction.response.send_message(f"Error: No configuration found with ID `{config_id}`.", ephemeral=True)
            return

        channel = interaction.guild.get_channel_or_thread(config_to_view.get("channel_id", 0))
        channel_mention = channel.mention if channel else f"ID: {config_to_view.get('channel_id', 'N/A')}"
        status = "Enabled" if config_to_view.get("is_enabled", False) else "Disabled"
        created_by_user = self.bot.get_user(config_to_view.get("created_by", 0))
        created_by_str = str(created_by_user) if created_by_user else f"ID: {config_to_view.get('created_by', 'N/A')}"
        
        try:
            created_at_dt = datetime.fromisoformat(config_to_view.get("created_at", ""))
            created_at_str = f"<t:{int(created_at_dt.timestamp())}:F>"
        except (ValueError, TypeError): 
            created_at_str = config_to_view.get("created_at", "N/A")


        embed = discord.Embed(
            title=f"Details for {config_to_view.get('name', f'Rule ID: {config_id[:8]}')}",
            color=await self.bot.get_embed_color(interaction.channel)
        )
        embed.add_field(name="Config ID", value=f"`{config_to_view.get('config_id', 'N/A')}`", inline=False)
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Recipient Phone", value=mask_phone_number(config_to_view.get("recipient_phone_number", "N/A")), inline=False)
        embed.add_field(name="Twilio Account SID", value=f"`{config_to_view.get('twilio_account_sid', 'N/A')}`", inline=False)
        embed.add_field(name="Twilio Auth Token", value="`********` (Masked)", inline=False) 
        embed.add_field(name="Twilio Sending Phone", value=mask_phone_number(config_to_view.get("twilio_phone_number", "N/A")), inline=False)
        embed.add_field(name="Created By", value=created_by_str, inline=True)
        embed.add_field(name="Created At", value=created_at_str, inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    
    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if not TWILIO_AVAILABLE:
            return 

        if message.author.bot or not message.guild or not message.content:
            return

        guild_id = message.guild.id
        configs = await self._get_guild_configs(guild_id)
        if not configs:
            return

        for conf in configs:
            if conf.get("is_enabled") and conf.get("channel_id") == message.channel.id:
                
                account_sid = conf.get("twilio_account_sid")
                auth_token = conf.get("twilio_auth_token")
                twilio_phone_number = conf.get("twilio_phone_number")
                recipient_phone_number = conf.get("recipient_phone_number")

                if not all([account_sid, auth_token, twilio_phone_number, recipient_phone_number]):
                    log.warning(
                        f"Skipping SMS for config '{conf.get('name', 'N/A')}' in guild {guild_id} "
                        f"due to missing Twilio credentials or recipient number."
                    )
                    continue

                sms_body = f"[{message.channel.name}] {message.author.display_name}: {message.content}"
                
                if len(sms_body) > 1600: 
                    sms_body = sms_body[:1597] + "..."
                
                try:
                    client = Client(account_sid, auth_token)
                    client.messages.create(
                        body=sms_body,
                        from_=twilio_phone_number,
                        to=recipient_phone_number
                    )
                    log.info(
                        f"SMS sent for config '{conf.get('name', 'N/A')}' in guild {guild_id} "
                        f"from channel {message.channel.id} to {mask_phone_number(recipient_phone_number)}."
                    )
                except TwilioRestException as e:
                    log.error(
                        f"Twilio API error for config '{conf.get('name', 'N/A')}' in guild {guild_id} "
                        f"to {mask_phone_number(recipient_phone_number)}: {e}"
                    )
                except Exception as e:
                    log.error(
                        f"Unexpected error sending SMS for config '{conf.get('name', 'N/A')}' in guild {guild_id}: {e}",
                        exc_info=True
                    )
