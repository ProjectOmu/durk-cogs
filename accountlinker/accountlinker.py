import discord
import asyncpg
import logging
import uuid
import asyncio
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from redbot.core import commands, Config, checks, app_commands
from redbot.core.bot import Red
from discord.ext import tasks
from discord.ui import Button, View, Modal, TextInput
from discord import Interaction, ButtonStyle, TextStyle

log = logging.getLogger("red.DurkCogs.AccountLinker")

async def get_linking_code_data(pool: asyncpg.Pool, code: uuid.UUID):
    conn = await pool.acquire()
    try:
        query = """
            SELECT lc.player_id, p.last_seen_user_name, lc.creation_time
            FROM rmc_linking_codes lc
            JOIN player p ON lc.player_id = p.user_id
            WHERE lc.code = $1;
        """
        return await conn.fetchrow(query, code)
    finally:
        await pool.release(conn)

async def get_discord_link_data(pool: asyncpg.Pool, discord_id: int):
    conn = await pool.acquire()
    try:
        query = """
            SELECT da.id, la.player_id
            FROM rmc_discord_accounts da
            LEFT JOIN rmc_linked_accounts la ON da.id = la.discord_id
            WHERE da.id = $1;
        """
        return await conn.fetchrow(query, discord_id)
    finally:
        await pool.release(conn)

async def remove_patron_and_link(conn: asyncpg.Connection, player_id: uuid.UUID):
    await conn.execute('DELETE FROM rmc_patrons WHERE player_id = $1;', player_id)
    await conn.execute('DELETE FROM rmc_linked_accounts WHERE player_id = $1;', player_id)

async def get_patron_tiers(pool: asyncpg.Pool):
    conn = await pool.acquire()
    try:
        query = 'SELECT id, discord_role, name, priority FROM rmc_patron_tiers ORDER BY priority ASC;'
        return await conn.fetch(query)
    finally:
        await pool.release(conn)

async def perform_linking(pool: asyncpg.Pool, discord_id: int, player_id: uuid.UUID, tier_id: int | None):
    conn = await pool.acquire()
    try:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO rmc_discord_accounts (id)
                VALUES ($1)
                ON CONFLICT (id) DO NOTHING;
            """, discord_id)
            await conn.execute("""
                INSERT INTO rmc_linked_accounts (discord_id, player_id)
                VALUES ($1, $2);
            """, discord_id, player_id)
            if tier_id is not None:
                await conn.execute("""
                    INSERT INTO rmc_patrons (player_id, tier_id)
                    VALUES ($1, $2)
                    ON CONFLICT (player_id) DO UPDATE SET tier_id = $2;
                """, player_id, tier_id)
            await conn.execute("""
                INSERT INTO rmc_linked_accounts_logs (discord_id, player_id, at)
                VALUES ($1, $2, $3);
            """, discord_id, player_id, datetime.now(timezone.utc))
        return True
    except Exception as e:
        log.error(f"Error during linking transaction for Discord ID {discord_id}: {e}", exc_info=True)
        return False
    finally:
        await pool.release(conn)

async def perform_unlinking(pool: asyncpg.Pool, discord_id: int):
    conn = await pool.acquire()
    try:
        async with conn.transaction():
            linked_data = await conn.fetchrow('SELECT player_id FROM rmc_linked_accounts WHERE discord_id = $1;', discord_id)
            if not linked_data:
                return False
            player_id = linked_data["player_id"]
            await conn.execute('DELETE FROM rmc_patrons WHERE player_id = $1;', player_id)
            await conn.execute('DELETE FROM rmc_linked_accounts WHERE discord_id = $1;', discord_id)
        return True
    except Exception as e:
        log.error(f"Error during unlinking transaction for Discord ID {discord_id}: {e}", exc_info=True)
        return False
    finally:
        await pool.release(conn)

class LinkAccountModal(Modal, title="Link SS14 Account"):
    account_code = TextInput(
        label="SS14 Linking Code (top left in the lobby)",
        style=TextStyle.short,
        placeholder="Enter the code you see in the game lobby",
        required=True,
        custom_id="account_code_input"
    )

    def __init__(self, cog_instance: 'AccountLinker', guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.guild_id = guild_id

    async def on_submit(self, interaction: Interaction):
        pool = await self.cog.get_pool_for_guild(self.guild_id)
        if not pool:
            await interaction.response.send_message("Database connection is not configured for this server. Please contact an admin.", ephemeral=True)
            return

        code_str = self.account_code.value.strip()
        try:
            link_code = uuid.UUID(code_str)
        except ValueError:
            await interaction.response.send_message(f"'{code_str}' is not a valid code format. Please get a new one from the game lobby.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            code_data = await get_linking_code_data(pool, link_code)
            if not code_data:
                await interaction.followup.send(f"No player found with code `{code_str}`. Please ensure it's correct and hasn't expired.", ephemeral=True)
                return
            if code_data["creation_time"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=1):
                 await interaction.followup.send(f"Code `{code_str}` was generated too long ago. Please get a new one.", ephemeral=True)
                 return

            player_id_to_link = code_data["player_id"]
            player_name = code_data["last_seen_user_name"]
            discord_user = interaction.user

            existing_link = await get_discord_link_data(pool, discord_user.id)

            if existing_link and existing_link["player_id"] is not None:
                existing_player_id = existing_link["player_id"]
                log.info(f"User {discord_user.id} already linked to player {existing_player_id} in Guild {self.guild_id}. Unlinking previous...")
                conn = await pool.acquire()
                try:
                    async with conn.transaction():
                        await remove_patron_and_link(conn, existing_player_id)
                    log.info(f"Successfully unlinked previous account for {discord_user.id} (Player: {existing_player_id}) in Guild {self.guild_id}.")
                except Exception as e:
                    log.error(f"Failed to remove previous link for {discord_user.id} (Player: {existing_player_id}) in Guild {self.guild_id}: {e}", exc_info=True)
                    await interaction.followup.send("Failed to remove your previous account link. Please try again or contact support.", ephemeral=True)
                    return
                finally:
                    await pool.release(conn)

            patron_tier_id = None
            highest_priority_tier_name = None
            if isinstance(discord_user, discord.Member):
                db_tiers = await get_patron_tiers(pool)
                user_role_ids = {role.id for role in discord_user.roles}
                for tier in db_tiers:
                    if tier["discord_role"] in user_role_ids:
                        patron_tier_id = tier["id"]
                        highest_priority_tier_name = tier["name"]
                        log.info(f"User {discord_user.id} has patron role for tier {highest_priority_tier_name} (ID: {patron_tier_id}) in Guild {self.guild_id}.")
                        break

            success = await perform_linking(pool, discord_user.id, player_id_to_link, patron_tier_id)

            if success:
                msg = f"Successfully linked your Discord account to SS14 account: **{player_name}**"
                if highest_priority_tier_name:
                    msg += f" with Patron Tier: **{highest_priority_tier_name}**."
                else:
                    msg += "."
                await interaction.followup.send(msg, ephemeral=True)
                log.info(f"Successfully linked Discord {discord_user.id} to Player {player_id_to_link} ({player_name}) in Guild {self.guild_id}")
            else:
                await interaction.followup.send("An error occurred while linking your account. Please try again later.", ephemeral=True)

        except asyncpg.PostgresError as db_err:
            log.error(f"Database error during linking for {interaction.user.id} in Guild {self.guild_id}: {db_err}", exc_info=True)
            await interaction.followup.send("A database error occurred. Please try again later or contact support.", ephemeral=True)
        except Exception as e:
            log.error(f"Unexpected error during linking for {interaction.user.id} in Guild {self.guild_id}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred. Please contact support.", ephemeral=True)

class DbConfigModal(Modal, title="Database Configuration"):
    db_user = TextInput(label="Database Username", style=TextStyle.short, required=True)
    db_pass = TextInput(label="Database Password", style=TextStyle.short, required=True)
    db_host = TextInput(label="Database Host (IP or Domain)", style=TextStyle.short, required=True)
    db_port = TextInput(label="Database Port", style=TextStyle.short, required=True, default="5432")
    db_name = TextInput(label="Database Name", style=TextStyle.short, required=True)

    def __init__(self, cog_instance: 'AccountLinker', guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.guild_id = guild_id

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        username = self.db_user.value.strip()
        password = self.db_pass.value
        host = self.db_host.value.strip()
        port = self.db_port.value.strip()
        dbname = self.db_name.value.strip()

        if not port.isdigit():
            await interaction.followup.send("Port must be a number.", ephemeral=True)
            return

        encoded_password = urllib.parse.quote(password)

        connection_string = f"postgresql://{username}:{encoded_password}@{host}:{port}/{dbname}"

        log.info(f"Attempting to set DB string for Guild {self.guild_id} (constructed from modal).")

        await self.cog.close_guild_pool(self.guild_id)

        try:
            await self.cog.config.guild_from_id(self.guild_id).db_connection_string.set(connection_string)
            log.info(f"Saved connection string for Guild {self.guild_id} to config.")
        except Exception as e:
            log.error(f"Failed to save connection string for Guild {self.guild_id} to config: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while saving the configuration.", ephemeral=True)
            return

        pool = await self.cog.get_pool_for_guild(self.guild_id)

        if pool:
            await interaction.followup.send(f"Database connection string saved and successfully tested for this server!", ephemeral=True)
        else:
            safe_debug_string = f"postgresql://{username}:********@{host}:{port}/{dbname}"
            await interaction.followup.send(f"Failed to connect using the provided details. Please check them and try again.\n(Attempted connection: `{safe_debug_string}`)", ephemeral=True)

class LinkAccountView(View):
    def __init__(self, cog_instance: 'AccountLinker'):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @discord.ui.button(label="Link your SS14 account here!", style=ButtonStyle.green, custom_id="link_ss14_account_button")
    async def link_button_callback(self, interaction: Interaction, button: Button):
        if not interaction.guild_id:
             await interaction.response.send_message("This button must be used within a server.", ephemeral=True)
             return
        await interaction.response.send_modal(LinkAccountModal(self.cog, interaction.guild_id))

class AccountLinker(commands.Cog):
    """Cog for linking SS14 accounts to Discord users using per-guild databases."""

    DEFAULT_GUILD = {
        "db_connection_string": None,
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier="AccountLinkerMultiDB", force_registration=True)
        self.config.register_guild(**self.DEFAULT_GUILD)
        self.guild_pools: Dict[int, asyncpg.Pool] = {}
        self.pool_locks: Dict[int, asyncio.Lock] = {}
        self.bot.add_view(LinkAccountView(self))
        self.patron_sync_task.start()

    async def get_pool_for_guild(self, guild_id: int) -> Optional[asyncpg.Pool]:
        if guild_id in self.guild_pools:
            return self.guild_pools[guild_id]

        if guild_id not in self.pool_locks:
            self.pool_locks[guild_id] = asyncio.Lock()

        async with self.pool_locks[guild_id]:
            if guild_id in self.guild_pools:
                return self.guild_pools[guild_id]

            log.debug(f"Attempting to retrieve DB config dict for Guild {guild_id}...")
            try:
                guild_data = await self.config.guild_from_id(guild_id).all()
                log.debug(f"Retrieved guild config dict for Guild {guild_id}: {guild_data!r}")
                conn_string = guild_data.get("db_connection_string")
            except Exception as e:
                 log.error(f"Error retrieving config dictionary for Guild {guild_id}: {e}", exc_info=True)
                 conn_string = None
            log.debug(f"Value for 'db_connection_string' in Guild {guild_id}: {conn_string!r}")
            if not conn_string:
                log.warning(f"Config dictionary check returned NO database connection string set for Guild {guild_id}.")
                return None

            try:
                log.info(f"Creating database connection pool for Guild {guild_id}...")
                pool = await asyncpg.create_pool(conn_string, min_size=2, max_size=10)
                async with pool.acquire() as conn:
                    await conn.execute("SELECT 1;")
                log.info(f"Database connection pool established and tested for Guild {guild_id}.")
                self.guild_pools[guild_id] = pool
                return pool
            except (asyncpg.PostgresError, OSError) as e:
                log.error(f"Failed to establish database connection pool for Guild {guild_id}: {e}", exc_info=True)
                return None
            except Exception as e:
                 log.error(f"Unexpected error during database initialization for Guild {guild_id}: {e}", exc_info=True)
                 return None

    async def close_guild_pool(self, guild_id: int):
        if guild_id in self.guild_pools:
            pool = self.guild_pools.pop(guild_id)
            if pool:
                await pool.close()
                log.info(f"Closed database connection pool for Guild {guild_id}.")
        if guild_id in self.pool_locks:
            del self.pool_locks[guild_id]


    async def cog_unload(self):
        self.patron_sync_task.cancel()
        guild_ids = list(self.guild_pools.keys())
        for guild_id in guild_ids:
            await self.close_guild_pool(guild_id)
        log.info("All guild database connection pools closed.")

    @app_commands.command(name="linkersetdb")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe()
    async def linkersetdb_slash(self, interaction: discord.Interaction):
        """Opens a modal to configure the database connection for this server (Admins only)."""
        if not interaction.guild_id:
             await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
             return
        await interaction.response.send_modal(DbConfigModal(self, interaction.guild_id))

    @commands.admin_or_permissions(manage_guild=True)
    @commands.command()
    @commands.guild_only()
    async def linksetup(self, ctx: commands.Context, *, message_text: str = "Click the button below to link your SS14 account!"):
        """Posts the account linking button message."""
        pool = await self.get_pool_for_guild(ctx.guild.id)
        if not pool:
             await ctx.send("The database connection is not configured for this server. Use `/linkersetdb` first.", ephemeral=True)
             return

        view = LinkAccountView(self)
        await ctx.send(message_text, view=view)
        try:
            await ctx.message.delete()
        except discord.Forbidden: pass
        except discord.HTTPException: pass


    @commands.command()
    @commands.guild_only()
    async def checklink(self, ctx: commands.Context, member: discord.Member = None):
        """Checks the linked SS14 account for yourself or another member."""
        pool = await self.get_pool_for_guild(ctx.guild.id)
        if not pool:
            await ctx.send("Database connection is not configured for this server.", ephemeral=True)
            return

        target_member = member or ctx.author

        conn = await pool.acquire()
        try:
            query = """
                SELECT p.last_seen_user_name
                FROM rmc_linked_accounts la
                JOIN player p ON la.player_id = p.user_id
                WHERE la.discord_id = $1;
            """
            result = await conn.fetchrow(query, target_member.id)

            if result:
                await ctx.send(f"{target_member.mention} is linked to SS14 account: **{result['last_seen_user_name']}**")
            else:
                await ctx.send(f"{target_member.mention} does not have an SS14 account linked.")
        except asyncpg.PostgresError as db_err:
             log.error(f"Database error during checklink for {target_member.id} in Guild {ctx.guild.id}: {db_err}", exc_info=True)
             await ctx.send("A database error occurred while checking the link.", ephemeral=True)
        finally:
            await pool.release(conn)


    @commands.command()
    @commands.guild_only()
    async def unlinkaccount(self, ctx: commands.Context):
        """Unlinks your Discord account from any associated SS14 account."""
        pool = await self.get_pool_for_guild(ctx.guild.id)
        if not pool:
            await ctx.send("Database connection is not configured for this server.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        success = await perform_unlinking(pool, ctx.author.id)

        if success:
            await ctx.send("Your SS14 account has been unlinked successfully.", ephemeral=True)
            log.info(f"User {ctx.author.id} successfully unlinked their account in Guild {ctx.guild.id}.")
        else:
            conn = await pool.acquire()
            try:
                is_linked = await conn.fetchval('SELECT 1 FROM rmc_linked_accounts WHERE discord_id = $1;', ctx.author.id)
                if is_linked:
                     await ctx.send("An error occurred while trying to unlink your account. Please try again later.", ephemeral=True)
                else:
                     await ctx.send("You do not have an SS14 account linked.", ephemeral=True)
            finally:
                 await pool.release(conn)

    @tasks.loop(minutes=5.0)
    async def patron_sync_task(self):
        """Periodically synchronizes patron status based on Discord roles for all configured guilds."""
        try:
            all_guild_data = await self.config.all_guilds()
            log.debug(f"Patron sync task: Raw all_guilds data: {all_guild_data!r}")
        except Exception as e:
            log.error(f"Patron sync task: Failed to retrieve all_guilds config: {e}", exc_info=True)
            return

        configured_guild_ids = []
        for guild_id, data in all_guild_data.items():
            if isinstance(data, dict) and data.get("db_connection_string"):
                 try:
                      configured_guild_ids.append(int(guild_id))
                      log.debug(f"Patron sync task: Found configured DB string for Guild {guild_id}")
                 except ValueError:
                      log.warning(f"Patron sync task: Found non-integer guild ID key in config: {guild_id}")
            else:
                 log.debug(f"Patron sync task: No DB string found in data for Guild {guild_id}. Data: {data!r}")


        if not configured_guild_ids:
            return

        log.debug(f"Patron sync task running for {len(configured_guild_ids)} configured guilds...")

        for guild_id in configured_guild_ids:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                log.warning(f"Patron sync task: Skipping configured guild {guild_id} as bot is not currently in it.")
                continue

            pool = await self.get_pool_for_guild(guild_id)
            if not pool:
                log.warning(f"Patron sync task: Skipping guild {guild_id} due to inability to get database pool.")
                continue

            log.debug(f"Patron sync task: Processing guild {guild.name} ({guild_id}).")
            conn = None
            try:
                conn = await pool.acquire()
                tiers = await conn.fetch('SELECT rmc_patron_tiers_id, discord_role, name, priority FROM rmc_patron_tiers ORDER BY priority ASC;')
                if not tiers:
                    log.warning(f"Patron sync task: No patron tiers found in database for Guild {guild_id}.")
                    await pool.release(conn)
                    continue

                linked_accounts = await conn.fetch("""
                    SELECT la.discord_id, la.player_id, p.last_seen_user_name, pat.tier_id as current_tier_id
                    FROM rmc_linked_accounts la
                    JOIN player p ON la.player_id = p.user_id
                    LEFT JOIN rmc_patrons pat ON la.player_id = pat.player_id;
                """)

                updated_count = 0
                removed_count = 0
                added_count = 0

                for link in linked_accounts:
                    discord_id = link["discord_id"]
                    player_id = link["player_id"]
                    current_db_tier_id = link["current_tier_id"]
                    player_name = link["last_seen_user_name"]

                    member = guild.get_member(discord_id)

                    highest_priority_role_tier_id = None
                    highest_priority_role_tier_name = None

                    if member:
                        user_role_ids = {role.id for role in member.roles}
                        for tier in tiers:
                            if tier["discord_role"] in user_role_ids:
                                highest_priority_role_tier_id = tier["rmc_patron_tiers_id"]
                                highest_priority_role_tier_name = tier["name"]
                                break

                    if highest_priority_role_tier_id != current_db_tier_id:
                        async with conn.transaction():
                            if current_db_tier_id is not None:
                                await conn.execute('DELETE FROM rmc_patrons WHERE player_id = $1;', player_id)
                                removed_count +=1
                                log.info(f"Patron sync (Guild {guild_id}): Removed patron status for {player_name} ({player_id}) / Discord {discord_id}. Reason: Role changed or user left guild.")
                            if highest_priority_role_tier_id is not None:
                                await conn.execute("""
                                    INSERT INTO rmc_patrons (player_id, tier_id) VALUES ($1, $2);
                                """, player_id, highest_priority_role_tier_id)
                                added_count +=1
                                log.info(f"Patron sync (Guild {guild_id}): Added/Updated patron status for {player_name} ({player_id}) / Discord {discord_id} to tier {highest_priority_role_tier_name} (ID: {highest_priority_role_tier_id}).")
                        updated_count +=1

                if updated_count > 0:
                    log.info(f"Patron sync task finished for Guild {guild_id}. Processed {len(linked_accounts)} linked accounts. DB changes: {updated_count} (Added: {added_count}, Removed: {removed_count})")
                else:
                     log.debug(f"Patron sync task finished for Guild {guild_id}. Processed {len(linked_accounts)} linked accounts. No changes needed.")

            except asyncpg.PostgresError as db_err:
                log.error(f"Patron sync task (Guild {guild_id}): Database error: {db_err}", exc_info=True)
            except discord.DiscordException as discord_err:
                 log.error(f"Patron sync task (Guild {guild_id}): Discord API error: {discord_err}", exc_info=True)
            except Exception as e:
                log.error(f"Patron sync task (Guild {guild_id}): Unexpected error: {e}", exc_info=True)
            finally:
                if conn:
                    await pool.release(conn)

    @patron_sync_task.before_loop
    async def before_patron_sync_task(self):
        await self.bot.wait_until_ready()
        log.info("Patron sync task starting loop...")
