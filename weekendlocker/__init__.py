from .weekendlocker import WeekendLocker

async def setup(bot):
    await bot.add_cog(WeekendLocker(bot))