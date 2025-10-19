from discord.ext import commands, tasks
import datetime, pytz, time as t
from discord.ui import Button, Select, View
import aiosqlite, random, typing
import sqlite3
import asyncio
import discord, logging
from discord.utils import get
from utils.Tools import *
import os
import aiohttp

db_folder = 'db'
db_file = 'giveaways.db'
db_path = os.path.join(db_folder, db_file)
connection = sqlite3.connect(db_path)
cursor = connection.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS Giveaway (
                    guild_id INTEGER,
                    host_id INTEGER,
                    start_time TIMESTAMP,
                    ends_at TIMESTAMP,
                    prize TEXT,
                    winners INTEGER,
                    message_id INTEGER,
                    channel_id INTEGER,
                    PRIMARY KEY (guild_id, message_id)
                )''')
connection.commit()
connection.close()

def convert(time):
    pos = ["s","m","h","d"]
    time_dict = {"s" : 1, "m" : 60, "h" : 3600 , "d" : 86400 , "f" : 259200}
    unit = time[-1]
    if unit not in pos:
        return
    try:
        val = int(time[:-1])
    except ValueError:
        return
    return val * time_dict[unit]

def WinnerConverter(winner):
    try:
        int(winner)
    except ValueError:
        try:
           return int(winner[:-1])
        except:
            return -4
    return winner

class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.connection = await aiosqlite.connect(db_path)
        self.cursor = await self.connection.cursor()
        await self.check_for_ended_giveaways()
        self.GiveawayEnd.start()

    async def cog_unload(self) -> None:
        await self.connection.close()

    async def check_for_ended_giveaways(self):
        await self.cursor.execute("SELECT ends_at, guild_id, message_id, host_id, winners, prize, channel_id FROM Giveaway WHERE ends_at <= ?", (datetime.datetime.now().timestamp(),))
        ended_giveaways = await self.cursor.fetchall()
        for giveaway in ended_giveaways:
            await self.end_giveaway(giveaway)

    async def end_giveaway(self, giveaway):
        try:
            current_time = datetime.datetime.now().timestamp()
            guild = self.bot.get_guild(int(giveaway[1]))
            if guild is None:
                await self.cursor.execute("DELETE FROM Giveaway WHERE message_id = ? AND guild_id = ?", (giveaway[2], giveaway[1]))
                await self.connection.commit()
                return

            channel = self.bot.get_channel(int(giveaway[6]))
            if channel is not None:
                try:
                    retries = 3
                    for attempt in range(retries):
                        try:
                            message = await channel.fetch_message(int(giveaway[2]))
                            break
                        except discord.NotFound:
                            await self.cursor.execute("DELETE FROM Giveaway WHERE message_id = ? AND guild_id = ?", (giveaway[2], giveaway[1]))
                            await self.connection.commit()
                            return
                        except aiohttp.ClientResponseError as e:
                            if e.status == 503:
                                if attempt < retries - 1:
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                                else:
                                    raise
                            else:
                                raise

                    users = [i.id async for i in message.reactions[0].users()]
                    if self.bot.user.id in users:
                        users.remove(self.bot.user.id)

                    if len(users) < 1:
                        await message.reply(f"No one won the **{giveaway[5]}** giveaway, due to Not enough participants.")
                        await self.cursor.execute("DELETE FROM Giveaway WHERE message_id = ? AND guild_id = ?", (message.id, message.guild.id))
                        await self.connection.commit()
                        return

                    winners_count = min(len(users), int(giveaway[4]))
                    winner = ', '.join(f'<@!{i}>' for i in random.sample(users, k=winners_count))

                    embed = discord.Embed(title=f"{giveaway[5]}",
                        description=f"Ended at <t:{int(current_time)}:R>\nHosted by <@{int(giveaway[3])}>\nWinner(s): {winner}",
                        color=0x000000)
                    embed.timestamp = discord.utils.utcnow()

                    embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1267699529130709075.png")
                    embed.set_footer(text=f"Ended at")
                    await message.edit(content="<a:gift:1197061264271212605> **GIVEAWAY ENDED** <a:Giveaway:1197061264271212605>", embed=embed)
                    await message.reply(f"<a:gift:1351861871690645505> Congrats {winner}, you won **{giveaway[5]}!**, Hosted by <@{int(giveaway[3])}>")
                    await self.cursor.execute("DELETE FROM Giveaway WHERE message_id = ? AND guild_id = ?", (message.id, message.guild.id))
                    await self.connection.commit()

                except (discord.HTTPException, aiohttp.ClientResponseError) as e:
                    logging.error(f"Error ending giveaway: {e}")

        except IndexError:
            logging.error(f"Giveaway data is corrupted or missing: {giveaway}")
            await self.cursor.execute("DELETE FROM Giveaway WHERE message_id = ? AND guild_id = ?", (giveaway[2], giveaway[1]))
            await self.connection.commit()

    @tasks.loop(seconds=5)
    async def GiveawayEnd(self):
        await self.cursor.execute("SELECT ends_at, guild_id, message_id, host_id, winners, prize, channel_id FROM Giveaway WHERE ends_at <= ?", (datetime.datetime.now().timestamp(),))
        ends_raw = await self.cursor.fetchall()
        for giveaway in ends_raw:
            await self.end_giveaway(giveaway)

    @commands.hybrid_command(description="Starts a new giveaway.")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    async def gstart(self, ctx,
                      time,
                      winners: int,
                      channel: typing.Optional[discord.TextChannel] = None,
                      *,
                      prize: str):

        # --- Determine target channel ---
        if channel is None:
            channel = ctx.channel  # default to current channel

        # --- Validate winners count ---
        if winners >=  15:
            embed = discord.Embed(title="⚠️ Access Denied",
                                  description=f"Cannot exceed more than 15 winners.",
                                  color=0x000000)
            message = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await message.delete()
            return

        await self.cursor.execute("SELECT message_id, channel_id FROM Giveaway WHERE guild_id = ?", (ctx.guild.id,))
        re = await self.cursor.fetchall()

        g_list = [i[0] for i in re]
        if len(g_list) >= 5:
            embed = discord.Embed(title="<:icons_warning:1327829522573430864> Access Denied",
                                  description=f"You can only host upto 5 giveaways in this Guild.", color=0x000000)
            message = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await message.delete()
            return

        converted = self.convert(time)
        if converted / 60 >= 50400:
            embed = discord.Embed(title="<:icons_warning:1327829522573430864> Access Denied",
                                  description=f"Time cannot exceed 31 days!", color=0x000000)
            message = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await message.delete()
            return

        if converted == -1:
            embed = discord.Embed(title="<:CrossIcon:1327829124894429235> Error",
                                  description=f"Invalid time format", color=0x000000)
            message = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await message.delete()
            return
        if converted == -2:
            embed = discord.Embed(title="<:CrossIcon:1327829124894429235> Error",
                                  description=f"Invalid time format. Please provide the time in numbers.",
                                  color=0x000000)
            message = await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await message.delete()
            return

        ends = (datetime.datetime.now().timestamp() + converted)

        # --- Prepare mentions ---
        mention_text = ""
        if "@here" in ctx.message.content:
            mention_text += "@here "
        if "@everyone" in ctx.message.content:
            mention_text += "@everyone "

        for role in ctx.message.role_mentions:
            mention_text += f"{role.mention} "
        for user in ctx.message.mentions:
            mention_text += f"{user.mention} "

        if mention_text:
            await channel.send(mention_text)

        # --- Prepare embed ---
        embed = discord.Embed(title=f"<a:gift:1197061264271212605> {prize}",
                              description=f"Winner(s): **{winners}**\nReact with <a:gift:1197061264271212605> to participate!\nEnds <t:{round(ends)}:R> (<t:{round(ends)}:f>)\n\nHosted by {ctx.author.mention}",
                              color=0x000000)

        ends1 = datetime.datetime.utcnow() + datetime.timedelta(seconds=converted)
        ends_utc = ends1.replace(tzinfo=datetime.timezone.utc)
        embed.timestamp = ends_utc
        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1267699441394126940.png")
        embed.set_footer(text=f"Ends at", icon_url=ctx.bot.user.avatar.url)

        message = await channel.send("<a:gift:1197061264271212605> **GIVEAWAY** <a:gift:1197061264271212605>", embed=embed)
        await message.add_reaction("🎉")

        await self.cursor.execute("INSERT INTO Giveaway(guild_id, host_id, start_time, ends_at, prize, winners, message_id, channel_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                                  (ctx.guild.id, ctx.author.id, datetime.datetime.now(), ends, prize, winners, message.id, channel.id))
        await self.connection.commit()

        try:
           await ctx.message.delete()
        except:
            pass

    # -------------------------------
    # All your other commands: gend, greroll, glist
    # Copy your original code for them below
    # -------------------------------

    def convert(self, time):
        pos = ["s", "m", "h", "d"]
        time_dict = {"s": 1, "m": 60, "h": 3600, "d": 86400, "f": 259200}

        unit = time[-1]
        if unit not in pos:
            return -1

        try:
            val = int(time[:-1])
        except ValueError:
            return -2

        return val * time_dict[unit]
