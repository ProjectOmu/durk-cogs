import discord
import io
from redbot.core import commands
from redbot.core.bot import Red

class MemberLister(commands.Cog):
    """
    A cog to list all server members.
    """

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def listmembers(self, ctx: commands.Context):
        """
        Scrapes all server members' names and sends them as a text file.
        
        The output is formatted as a string array like: "NAME", "NAME2", "NAME3"
        """

        await ctx.typing()

        guild = ctx.guild

        member_names = [member.name.replace('"', '\\"') for member in guild.members]
        
        quoted_names = [f'"{name}"' for name in member_names]
        
        output_string = ", ".join(quoted_names)

        if not output_string:
            await ctx.send("Could not find any members to list.")
            return

        file_content = io.StringIO(output_string)
        file = discord.File(file_content, filename=f"{guild.name}_members.txt")
        
        await ctx.send(f"Here is the list of all {len(member_names)} members in **{guild.name}**.", file=file)
