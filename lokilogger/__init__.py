
from .lokilogger import LokiLogger

async def setup(bot):
    await bot.add_cog(LokiLogger(bot))