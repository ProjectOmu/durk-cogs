import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red

class RoleSyncer(commands.Cog):
    """Cog for syncing roles between multiple discord servers"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier="rolesync")
        default_global = {
            "sync_groups": {},
            "enabled": True
        }
        self.config.register_global(**default_global)

    @commands.group()
    @checks.admin_or_permissions(administrator=True)
    async def rolesync(self, ctx: commands.Context):
        """Manage role synchronization settings."""
        pass

    @rolesync.command(name="create")
    async def rolesync_create(self, ctx: commands.Context, group_name: str):
        """Creates a new role synchronization group."""
        async with self.config.sync_groups() as groups:
            if group_name in groups:
                await ctx.send(f"Group '{group_name}' already exists.")
                return
            groups[group_name] = []
        await ctx.send(f"Sync group '{group_name}' created.")

    @rolesync.command(name="delete")
    async def rolesync_delete(self, ctx: commands.Context, group_name: str):
        """Deletes a role synchronization group."""
        async with self.config.sync_groups() as groups:
            if group_name not in groups:
                await ctx.send(f"Group '{group_name}' not found.")
                return
            del groups[group_name]
        await ctx.send(f"Sync group '{group_name}' deleted.")

    @rolesync.command(name="list")
    async def rolesync_list(self, ctx: commands.Context):
        """Lists all role synchronization groups and their servers."""
        groups = await self.config.sync_groups()
        if not groups:
            await ctx.send("No sync groups configured.")
            return

        msg = "**Role Synchronization Groups:**\n"
        for name, guilds in groups.items():
            guild_list = ", ".join(str(g) for g in guilds) or "No servers"
            msg += f"- **{name}**: {guild_list}\n"
        await ctx.send(msg)

    @rolesync.command(name="addserver")
    async def rolesync_addserver(self, ctx: commands.Context, group_name: str, guild_id: int):
        """Adds a server (by ID) to a sync group."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            await ctx.send(f"Could not find a server with ID {guild_id}. Make sure the bot is in that server.")
            return

        async with self.config.sync_groups() as groups:
            if group_name not in groups:
                await ctx.send(f"Group '{group_name}' not found.")
                return
            if guild_id in groups[group_name]:
                await ctx.send(f"Server {guild.name} ({guild_id}) is already in group '{group_name}'.")
                return
            groups[group_name].append(guild_id)
        await ctx.send(f"Server {guild.name} ({guild_id}) added to sync group '{group_name}'.")

    @rolesync.command(name="removeserver")
    async def rolesync_removeserver(self, ctx: commands.Context, group_name: str, guild_id: int):
        """Removes a server (by ID) from a sync group."""
        async with self.config.sync_groups() as groups:
            if group_name not in groups:
                await ctx.send(f"Group '{group_name}' not found.")
                return
            if guild_id not in groups[group_name]:
                guild_name = self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else guild_id
                await ctx.send(f"Server {guild_name} is not in group '{group_name}'.")
                return
            groups[group_name].remove(guild_id)
            guild_name = self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else guild_id
        await ctx.send(f"Server {guild_name} removed from sync group '{group_name}'.")

    @rolesync.command(name="toggle")
    async def rolesync_toggle(self, ctx: commands.Context):
        """Toggles role synchronization globally."""
        current_status = await self.config.enabled()
        await self.config.enabled.set(not current_status)
        status = "enabled" if not current_status else "disabled"
        await ctx.send(f"Role synchronization is now globally {status}.")

    @rolesync.command(name="forcesync")
    @checks.admin_or_permissions(administrator=True)
    async def rolesync_forcesync(self, ctx: commands.Context):
        """Forces a role synchronization across all configured groups and servers."""
        if not await self.config.enabled():
            await ctx.send("Role synchronization is globally disabled. Enable it first with `[p]rolesync toggle`.")
            return

        await ctx.send("Starting full role synchronization... This may take a while.")
        sync_groups = await self.config.sync_groups()
        if not sync_groups:
            await ctx.send("No sync groups configured.")
            return

        processed_users = 0
        sync_actions = 0

        for group_name, guild_ids in sync_groups.items():
            if len(guild_ids) < 2:
                continue

            guild_pairs = []
            guild_objects = [self.bot.get_guild(gid) for gid in guild_ids]
            guild_objects = [g for g in guild_objects if g]

            if len(guild_objects) < 2:
                continue

            for i in range(len(guild_objects)):
                for j in range(i + 1, len(guild_objects)):
                    guild_pairs.append((guild_objects[i], guild_objects[j]))

            for guild_a, guild_b in guild_pairs:
                for member_a in guild_a.members:
                    if member_a.bot: continue
                    member_b = guild_b.get_member(member_a.id)
                    if member_b:
                        processed_users += 1
                        roles_a_names = {r.name for r in member_a.roles}
                        roles_b_names = {r.name for r in member_b.roles}
                        to_add_b = roles_a_names - roles_b_names
                        to_remove_b = roles_b_names - roles_a_names
                        if to_add_b or to_remove_b:
                            await self._sync_member_roles(member_a, guild_a, member_b, guild_b, to_add_b, to_remove_b)
                            sync_actions += len(to_add_b) + len(to_remove_b)

                for member_b in guild_b.members:
                     if member_b.bot: continue
                     member_a = guild_a.get_member(member_b.id)
                     if member_a:
                        roles_a_names = {r.name for r in member_a.roles}
                        roles_b_names = {r.name for r in member_b.roles}
                        to_add_a = roles_b_names - roles_a_names
                        to_remove_a = roles_a_names - roles_b_names
                        if to_add_a or to_remove_a:
                            await self._sync_member_roles(member_b, guild_b, member_a, guild_a, to_add_a, to_remove_a)
                            sync_actions += len(to_add_a) + len(to_remove_a)


        await ctx.send(f"Full role synchronization complete. Processed {processed_users} user instances across server pairs, performing {sync_actions} role adjustments.")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Listens for role changes and syncs them."""
        if not await self.config.enabled():
            return
        if before.roles == after.roles:
            return

        guild = after.guild
        user = after

        sync_groups = await self.config.sync_groups()
        relevant_groups = self._get_relevant_groups(guild.id, sync_groups)

        if not relevant_groups:
            return

        before_role_names = {r.name for r in before.roles}
        after_role_names = {r.name for r in after.roles}
        added_roles = after_role_names - before_role_names
        removed_roles = before_role_names - after_role_names

        if not added_roles and not removed_roles:
            return

        for group_name in relevant_groups:
            target_guild_ids = sync_groups[group_name]
            for target_guild_id in target_guild_ids:
                if target_guild_id == guild.id:
                    continue

                target_guild = self.bot.get_guild(target_guild_id)
                if not target_guild:
                    continue

                target_member = target_guild.get_member(user.id)
                if not target_member:
                    continue

                await self._sync_member_roles(user, guild, target_member, target_guild, added_roles, removed_roles)

    def _get_relevant_groups(self, guild_id: int, all_groups: dict) -> list[str]:
        """Finds the sync groups a specific guild belongs to."""
        relevant = []
        for group_name, guild_ids in all_groups.items():
            if guild_id in guild_ids:
                relevant.append(group_name)
        return relevant

    async def _sync_member_roles(self, source_member: discord.Member, source_guild: discord.Guild,
                                 target_member: discord.Member, target_guild: discord.Guild,
                                 roles_to_add_names: set[str], roles_to_remove_names: set[str]):
        """Adds/removes roles on the target member based on changes in the source."""
        roles_to_add_target = []
        roles_to_remove_target = []

        for role_name in roles_to_add_names:
            role = discord.utils.get(target_guild.roles, name=role_name)
            if role and role not in target_member.roles:
                if target_guild.me.top_role > role:
                    roles_to_add_target.append(role)
                else:
                    print(f"RoleSync: Cannot add role '{role.name}' in {target_guild.name} - Bot hierarchy too low.")


        for role_name in roles_to_remove_names:
            role = discord.utils.get(target_guild.roles, name=role_name)
            if role and role in target_member.roles:
                if target_guild.me.top_role > role:
                    roles_to_remove_target.append(role)
                else:
                    print(f"RoleSync: Cannot remove role '{role.name}' in {target_guild.name} - Bot hierarchy too low.")

        try:
            if roles_to_add_target:
                await target_member.add_roles(*roles_to_add_target, reason=f"RoleSync from {source_guild.name}")
            if roles_to_remove_target:
                await target_member.remove_roles(*roles_to_remove_target, reason=f"RoleSync from {source_guild.name}")
        except discord.Forbidden:
            print(f"RoleSync: Missing permissions to modify roles for {target_member} in {target_guild.name}.")
        except discord.HTTPException as e:
             print(f"RoleSync: Failed to modify roles for {target_member} in {target_guild.name}: {e}")
