from .ahelp_replies import ahelp_replies

async def setup(bot):
    await bot.add_cog(ahelp_replies(bot))