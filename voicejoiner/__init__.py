from .voiceconnector import VoiceConnector

async def setup(bot):
    cog = VoiceConnector(bot)
    await bot.add_cog(cog)
