import aiohttp
import asyncio
import discord
from discord import ChannelType, Message, Role
import json
from redbot.core import checks, commands, Config
from red_commons.logging import getLogger

log = getLogger("red.april-cogs.ahelpreplies")
starter_messages = {}

# Input class for the discord modal
class Input(discord.ui.Modal, title='Input server details'):
    identifier = discord.ui.TextInput(label='Server Identifier', placeholder='grimbly', required=True)
    display_name = discord.ui.TextInput(label='Display Name',
                                 placeholder='Grimbly Station',
                                 required = True)
    server_ip = discord.ui.TextInput(label='Server IP',
                                 placeholder='localhost:1212 (DO NOT USE A DOMAIN)',
                                 required=True)
    token = discord.ui.TextInput(label='API Token',
                                 placeholder='Server\'s api.token value in server_config.toml',
                                 required = True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Processing...", ephemeral=True)
        self.stop()

# Button to bring up the modal
class Button(discord.ui.View):
    def __init__(self, member):
        self.member = member
        super().__init__()
        self.modal = None

    @discord.ui.button(label='Add', style=discord.ButtonStyle.green)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.member != interaction.user:
            return await interaction.response.send_message("You cannot use this.", ephemeral=True)

        self.modal = Input()
        await interaction.response.send_modal(self.modal)
        await self.modal.wait()
        self.stop()

ACTION_TIMEOUT = 5

async def get_user_id(session: aiohttp.ClientSession, username) -> str | None:
    async with session.get(f"https://auth.spacestation14.com/api/query/name?name={username}") as resp:
        if resp.status == 404:
            return
        
        response = await resp.json()
        return response["userId"]

async def send_reply(session: aiohttp.ClientSession, message, server, username: str) -> tuple[int, str] | None:
    userId = await asyncio.wait_for(
        get_user_id(session, username), 
        timeout=ACTION_TIMEOUT
    )

    if userId == None:
        log.warning("No userId found.")
        return

    async def load() -> tuple[int, str]:
        role: Role = message.author.top_role
        data = json.dumps({
            "Guid": userId,
            "Username": message.author.display_name,
            "Text": message.content,
            "UserOnly": False,
            "WebhookUpdate": True,
            "RoleName": role.name,
            "RoleColor": str(role.color)
        })
        
        session.headers['Authorization'] = f'SS14Token {server["token"]}'
        async with session.post(f'http://{server["server_ip"]}/admin/actions/send_bwoink', data = data) as resp:
            return resp.status, await resp.text()

    return await asyncio.wait_for(
        load(), 
        timeout=ACTION_TIMEOUT
    )

class ahelp_replies(commands.Cog):
    """AHelp replies for discord-game communication."""

    cached: dict[int, str] = {}

    def __init__(self, bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = Config.get_conf(self, identifier = 683728)

        default_guild = {
            "channels": {},
            "servers": {},
        }

        self.config.register_guild(**default_guild, force_registration=True)
        self.bot = bot
    
    async def handle_thread(self, message: Message, starter_message: Message, cur_server) -> None:
        first_parenthesis = starter_message.author.name.find("(")
        username = starter_message.author.name

        if first_parenthesis != -1:
            username = starter_message.author.name[:first_parenthesis - 1]

        if username.isspace():
            return
        
        async with aiohttp.ClientSession(headers = {'accept': 'application/json'}) as session:
            try:
                status, response = await send_reply(session, message, cur_server, username)

                if status != 200:
                    await message.channel.send(f"Failed:\n{status}: {response}")
                else:
                    await message.delete()
            except asyncio.TimeoutError:
                    await message.channel.send("Server timed out.")
                    return

            except Exception:
                await message.channel.send(
                    f"An Unknown error occured while trying to request this server to update, Logging to console...")
                
                log.exception(f'An error occurred while trying to reply on server **{cur_server["display_name"]}.')
                return

    @commands.Cog.listener()
    async def on_message(self, message: Message) -> None:
        if message.guild == None:
            return

        guild_settings = self.config.guild(message.guild)

        servers = await guild_settings.servers()
        channels = await guild_settings.channels()

        if servers is None or channels is None:
            return

        if message.webhook_id == None and message.author.bot == True:
            return

        channel_to_use = message.channel

        if channel_to_use.type == ChannelType.public_thread:
            if channel_to_use.starter_message == None or channel_to_use.starter_message.channel == None:
                return
            channel_to_use = channel_to_use.starter_message.channel

        if channels.get(str(channel_to_use.id)) == None:
            return
        
        server_ids = channels.get(str(channel_to_use.id))

        if message.channel.type == ChannelType.text and message.webhook_id != None:
            await message.create_thread(name = "Replies")
            return

        for idx, server_id in enumerate(server_ids):
            if servers.get(server_id) == None:
                channels[str(channel_to_use.id)].pop(idx)
                continue

            cur_server = servers[server_id]
            
            if message.channel.type == ChannelType.public_thread:
                return await self.handle_thread(message, message.channel.starter_message, cur_server)

    @commands.hybrid_group()
    @checks.admin()
    async def ahrcfg(self, ctx: commands.Context) -> None:
        """
        Commands for configuring the ahelp replies cog.
        """
        pass

    @ahrcfg.command()
    async def add(self, ctx: commands.Context) -> None:
        """
        Adds a server.
        """
        view = Button(member = ctx.author)

        await ctx.send("To add a server press this button.", view=view)
        await view.wait()

        if view.modal is None:
            return

        async with self.config.guild(ctx.guild).servers() as cur_servers:
            if view.modal.identifier.value in cur_servers:
                await ctx.send("A server with that name already exists.")
                return

            cur_servers[view.modal.identifier.value] = {
                "server_ip": view.modal.server_ip.value,
                "display_name": view.modal.display_name.value,
                "token": view.modal.token.value
            }

        await ctx.send("Server added successfully.")
    
    @ahrcfg.command()
    async def remove(self, ctx: commands.Context, identifier: str) -> None:
        """
        Removes a server.
        """
        
        async with self.config.guild(ctx.guild).channels() as channels:
            old_channels = channels.copy()
            for channel_id, channel_linked_identifier in old_channels.items():
                if channel_linked_identifier == identifier:
                    del channels[channel_id]
                    await ctx.send("Channel found, deleting.")

            old_channels = None

        async with self.config.guild(ctx.guild).servers() as servers:
            if not servers.get(identifier):
                await ctx.send("No server found.")
                return
            del servers[identifier]

        await ctx.send("Server removed successfully.")

    @ahrcfg.command()
    async def use_channel(self, ctx: commands.Context, identifier: str) -> None:
        """
        Sets this channel as the one to watch for AHelp relays from.
        """

        servers = await self.config.guild(ctx.guild).servers()
        
        if len(servers) == 0 or not identifier in servers:
            await ctx.send("No server matching that identifier was found.")
            return

        async with self.config.guild(ctx.guild).channels() as channels:
            for server_ids in channels:
                if identifier in server_ids:
                    idx = channels.index(identifier)
                    server_ids.pop(idx)

            if channels.get(str(ctx.channel.id)) == None:
                channels[str(ctx.channel.id)] = []

            channels[str(ctx.channel.id)].append(identifier)

        await ctx.send(f'Successfully added AHelp relay channel <#{ctx.channel.id}> for **{servers[identifier]["display_name"]}**!\nAny previous channel that server had is now replaced.')

    @ahrcfg.command()
    async def list(self, ctx: commands.Context):
        """
        Lists all servers associated with this guild without exposing sensitive information.
        """

        guild_config = self.config.guild(ctx.guild)
        servers = await guild_config.servers()
        
        if len(servers) == 0:
            await ctx.send(f"No servers are associated with ``{ctx.guild.name}``")
            return
        
        servers_msg = "Servers:"

        for identifier, server in servers.items():
            servers_msg += f'\n``{server["display_name"]}``, identified as ``{identifier}``'
        
        ctx.send(servers_msg)

        


