from redbot.core.bot import Red
from .filter import MessageFilter

__red_end_user_data_statement__ = "This cog does not store user data."

async def setup(bot: Red) -> None:
    await bot.add_cog(MessageFilter(bot))
