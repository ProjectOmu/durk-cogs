from .mastodonfeeder import MastodonFeeder

async def setup(bot):
    await bot.add_cog(MastodonFeeder(bot))