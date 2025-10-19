import discord
from discord.ext import commands


class Loggingdrop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    """Logging commands"""

    def help_custom(self):
              emoji = '<:logging:1392124867872165969>'
              label = "Logging"
              description = "Advance Logging Command"
              return emoji, label, description

    @commands.group()
    async def __Logging__(self, ctx: commands.Context):
        """`>loggingsetup`, `>removelogs`"""