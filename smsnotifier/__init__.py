from .smsnotifier import SMSNotifier

async def setup(bot):
    cog = SMSNotifier(bot)
    await bot.add_cog(cog)