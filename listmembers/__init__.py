from .memberlister import MemberLister

async def setup(bot):
    await bot.add_cog(MemberLister(bot))
