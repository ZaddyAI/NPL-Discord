import discord

from discord.ext import commands

class _inviteTracker(commands.Cog):

    def __init__(self, bot):

        self.bot = bot

    """Invite Tracker"""

    def help_custom(self):

              emoji = '<:InviteTracker:1392125185817051239>'

              label = "Invite Tracker"

              description = "Show you Commands of Invite Tracker"

              return emoji, label, description

    @commands.group()

    async def __InviteTracker__(self, ctx: commands.Context):

        """`>Invite enable` , `>Invite disable `, `>invites` , `>resetinvites` , `>addinvites` , `>removeinvites` , `>resetserverinvites` """