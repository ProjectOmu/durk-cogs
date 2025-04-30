import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
import logging
from typing import Set

log = logging.getLogger("red.durk-cogs.rolesyncer")

class RoleSyncer(commands.Cog):
    """Cog for syncing specific roles between multiple discord servers based on groups."""

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
            groups[group_name] = {"guilds": [], "roles": []}
        await ctx.send(f"Sync group '{group_name}' created. Use `addserver` and `addrole` to configure it.")

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
        """Lists all role synchronization groups, their servers, and synced roles."""
        groups = await self.config.sync_groups()
        if not groups:
            await ctx.send("No sync groups configured.")
            return

        msg = "**Role Synchronization Groups:**\n"
        for name, data in groups.items():
            guild_list = ", ".join(str(g) for g in data.get("guilds", [])) or "No servers"
            role_list = ", ".join(f"`{r}`" for r in data.get("roles", [])) or "No roles configured"
            msg += f"- **{name}**:\n  - Servers: {guild_list}\n  - Synced Roles: {role_list}\n"
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
            if guild_id in groups[group_name]["guilds"]:
                await ctx.send(f"Server {guild.name} ({guild_id}) is already in group '{group_name}'.")
                return
            groups[group_name]["guilds"].append(guild_id)
        await ctx.send(f"Server {guild.name} ({guild_id}) added to sync group '{group_name}'.")

    @rolesync.command(name="removeserver")
    async def rolesync_removeserver(self, ctx: commands.Context, group_name: str, guild_id: int):
        """Removes a server (by ID) from a sync group."""
        async with self.config.sync_groups() as groups:
            if group_name not in groups:
                await ctx.send(f"Group '{group_name}' not found.")
                return
            if guild_id not in groups[group_name]["guilds"]:
                guild_name = self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else guild_id
                await ctx.send(f"Server {guild_name} is not in group '{group_name}'.")
                return
            groups[group_name]["guilds"].remove(guild_id)
            guild_name = self.bot.get_guild(guild_id).name if self.bot.get_guild(guild_id) else guild_id
        await ctx.send(f"Server {guild_name} removed from sync group '{group_name}'.")

    @rolesync.command(name="addrole")
    async def rolesync_addrole(self, ctx: commands.Context, group_name: str, *, role_name: str):
        """Adds a role name to be synced for a specific group. Case-sensitive."""
        async with self.config.sync_groups() as groups:
            if group_name not in groups:
                await ctx.send(f"Group '{group_name}' not found.")
                return
            if role_name in groups[group_name]["roles"]:
                await ctx.send(f"Role name `{role_name}` is already configured for sync in group '{group_name}'.")
                return
            groups[group_name]["roles"].append(role_name)
        await ctx.send(f"Role name `{role_name}` will now be synced for group '{group_name}'.")

    @rolesync.command(name="removerole")
    async def rolesync_removerole(self, ctx: commands.Context, group_name: str, *, role_name: str):
        """Removes a role name from being synced for a specific group."""
        async with self.config.sync_groups() as groups:
            if group_name not in groups:
                await ctx.send(f"Group '{group_name}' not found.")
                return
            if role_name not in groups[group_name]["roles"]:
                await ctx.send(f"Role name `{role_name}` is not configured for sync in group '{group_name}'.")
                return
            groups[group_name]["roles"].remove(role_name)
        await ctx.send(f"Role name `{role_name}` will no longer be synced for group '{group_name}'.")


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
        """Forces a synchronization of configured roles across all groups and servers."""
        if not await self.config.enabled():
            await ctx.send("Role synchronization is globally disabled. Enable it first with `[p]rolesync toggle`.")
            return

        await ctx.send("Starting full role synchronization for configured roles... This may take a while.")
        sync_groups = await self.config.sync_groups()
        if not sync_groups:
            await ctx.send("No sync groups configured.")
            return

        processed_users = 0
        sync_actions = 0

        for group_name, group_data in sync_groups.items():
            guild_ids = group_data.get("guilds", [])
            allowed_roles = set(group_data.get("roles", []))

            if not allowed_roles:
                log.debug(f"Skipping group '{group_name}' in forcesync: No roles configured.")
                continue

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
                log.debug(f"Forcesync: Processing pair {guild_a.name} <-> {guild_b.name} for group '{group_name}'")
                for member_a in guild_a.members:
                    if member_a.bot: continue
                    member_b = guild_b.get_member(member_a.id)
                    if member_b:
                        processed_users += 1
                        roles_a_names = {r.name for r in member_a.roles}
                        roles_b_names = {r.name for r in member_b.roles}

                        relevant_roles_a = roles_a_names.intersection(allowed_roles)
                        relevant_roles_b = roles_b_names.intersection(allowed_roles)

                        to_add_b = relevant_roles_a - relevant_roles_b
                        to_remove_b = relevant_roles_b - relevant_roles_a

                        if to_add_b or to_remove_b:
                            log.debug(f"Forcesync A->B: Syncing {member_a} ({guild_a.name}) -> {member_b} ({guild_b.name}). Add: {to_add_b}, Remove: {to_remove_b}")
                            await self._sync_member_roles(member_a, guild_a, member_b, guild_b, to_add_b, to_remove_b, allowed_roles)
                            sync_actions += len(to_add_b) + len(to_remove_b)

                for member_b in guild_b.members:
                     if member_b.bot: continue
                     member_a = guild_a.get_member(member_b.id)
                     if member_a:
                        roles_a_names = {r.name for r in member_a.roles}
                        roles_b_names = {r.name for r in member_b.roles}

                        relevant_roles_a = roles_a_names.intersection(allowed_roles)
                        relevant_roles_b = roles_b_names.intersection(allowed_roles)

                        to_add_a = relevant_roles_b - relevant_roles_a
                        to_remove_a = relevant_roles_a - relevant_roles_b

                        if to_add_a or to_remove_a:
                            log.debug(f"Forcesync B->A: Syncing {member_b} ({guild_b.name}) -> {member_a} ({guild_a.name}). Add: {to_add_a}, Remove: {to_remove_a}")
                            await self._sync_member_roles(member_b, guild_b, member_a, guild_a, to_add_a, to_remove_a, allowed_roles)
                            sync_actions += len(to_add_a) + len(to_remove_a)


        await ctx.send(f"Full role synchronization complete. Processed {processed_users} user instances across server pairs, performing {sync_actions} role adjustments based on configured roles.")-

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Listens for role changes and syncs configured roles."""
        if not await self.config.enabled():
            return
        if before.roles == after.roles or after.bot:
            return

        guild = after.guild
        user = after

        sync_groups_data = await self.config.sync_groups()
        relevant_groups = self._get_relevant_groups(guild.id, sync_groups_data)

        if not relevant_groups:
            return

        before_role_names = {r.name for r in before.roles}
        after_role_names = {r.name for r in after.roles}
        added_role_names = after_role_names - before_role_names
        removed_role_names = before_role_names - after_role_names

        if not added_role_names and not removed_role_names:
             return

        for group_name in relevant_groups:
            group_data = sync_groups_data[group_name]
            target_guild_ids = group_data.get("guilds", [])
            allowed_roles = set(group_data.get("roles", []))

            if not allowed_roles:
                log.debug(f"Skipping group '{group_name}' in on_member_update: No roles configured.")
                continue

            relevant_added = added_role_names.intersection(allowed_roles)
            relevant_removed = removed_role_names.intersection(allowed_roles)

            if not relevant_added and not relevant_removed:
                log.debug(f"Skipping group '{group_name}' for member {user}: Changes ({added_role_names}, {removed_role_names}) not relevant to configured roles ({allowed_roles}).")
                continue

            for target_guild_id in target_guild_ids:
                if target_guild_id == guild.id:
                    continue

                target_guild = self.bot.get_guild(target_guild_id)
                if not target_guild:
                    log.warning(f"Target guild {target_guild_id} not found or bot not in it.")
                    continue

                target_member = target_guild.get_member(user.id)
                if not target_member:
                    continue

                log.debug(f"Syncing {user} from {guild.name} to {target_guild.name} (Group: {group_name}). Add: {relevant_added}, Remove: {relevant_removed}")
                await self._sync_member_roles(user, guild, target_member, target_guild, relevant_added, relevant_removed, allowed_roles)

    def _get_relevant_groups(self, guild_id: int, all_groups: dict) -> list[str]:
        """Finds the sync groups a specific guild belongs to."""
        relevant = []
        for group_name, group_data in all_groups.items():
            if guild_id in group_data.get("guilds", []):
                relevant.append(group_name)
        return relevant

    async def _sync_member_roles(self, source_member: discord.Member, source_guild: discord.Guild,
                                 target_member: discord.Member, target_guild: discord.Guild,
                                 roles_to_add_names: Set[str], roles_to_remove_names: Set[str],
                                 allowed_roles: Set[str]):
        """Adds/removes configured roles on the target member based on changes in the source."""
        roles_to_add_target = []
        roles_to_remove_target = []

        final_roles_to_add = roles_to_add_names.intersection(allowed_roles)
        final_roles_to_remove = roles_to_remove_names.intersection(allowed_roles)

        for role_name in final_roles_to_add:
            role = discord.utils.get(target_guild.roles, name=role_name)
            if role and role not in target_member.roles:
                if target_guild.me.top_role > role:
                    roles_to_add_target.append(role)
                else:
                    log.warning(f"RoleSync: Cannot add role '{role.name}' to {target_member} in {target_guild.name} - Bot hierarchy too low.")

        for role_name in final_roles_to_remove:
            role = discord.utils.get(target_guild.roles, name=role_name)
            if role and role in target_member.roles:
                if target_guild.me.top_role > role:
                    roles_to_remove_target.append(role)
                else:
                    log.warning(f"RoleSync: Cannot remove role '{role.name}' from {target_member} in {target_guild.name} - Bot hierarchy too low.")

        try:
            if roles_to_add_target:
                await target_member.add_roles(*roles_to_add_target, reason=f"RoleSync from {source_guild.name}")
                log.info(f"Added roles {[r.name for r in roles_to_add_target]} to {target_member} in {target_guild.name}")
            if roles_to_remove_target:
                await target_member.remove_roles(*roles_to_remove_target, reason=f"RoleSync from {source_guild.name}")
                log.info(f"Removed roles {[r.name for r in roles_to_remove_target]} from {target_member} in {target_guild.name}")
        except discord.Forbidden:
            log.error(f"RoleSync: Missing permissions to modify roles for {target_member} in {target_guild.name}.")
        except discord.HTTPException as e:
            log.error(f"RoleSync: Failed to modify roles for {target_member} in {target_guild.name}: {e}")
