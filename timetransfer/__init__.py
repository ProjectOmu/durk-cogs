
from .timetransfer import TimeTransfer

async def setup(bot):
    await bot.add_cog(TimeTransfer(bot))