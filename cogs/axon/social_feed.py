import discord
from discord.ext import commands


class _socialfeed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    """Social Feed commands"""

    def help_custom(self):
        emoji = '📰'
        label = "Social Feed Commands"
        description = "Manage social media feeds with dialog boxes"
        return emoji, label, description

    @commands.group()
    async def __SocialFeed__(self, ctx: commands.Context):
        """`socialfeed`, `socialfeed_remove`, `socialfeed_list`"""
