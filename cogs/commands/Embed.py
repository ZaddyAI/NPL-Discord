import discord
from discord.ext import commands
from discord.ui import View, Select, Button
import asyncio

class Embed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="embed")
    @commands.has_permissions(manage_messages=True)
    async def _embed(self, ctx):
        interaction_user = ctx.author
        embed = discord.Embed(
            title="Edit your Embed!",
            description="Select options from the menu to customize your embed.",
            color=0x2F3136
        )

        def chk(m):
            return m.author.id == interaction_user.id and not m.author.bot

        # --- Select Menu Callback ---
        async def select_callback(interaction):
            if interaction.user.id != interaction_user.id:
                await interaction.response.send_message("This menu is not yours!", ephemeral=True)
                return

            await interaction.response.defer()
            value = select.values[0]

            try:
                if value == "Title":
                    await ctx.send("Enter the **Title** of the embed:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.title = msg.content

                elif value == "Description":
                    await ctx.send("Enter the **Description** of the embed:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.description = msg.content

                elif value == "Color":
                    await ctx.send("Enter the **Color** as HEX (e.g., #FF0000):")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.color = discord.Colour(int(msg.content.strip("#"), 16))

                elif value == "Thumbnail":
                    await ctx.send("Enter the **Thumbnail URL**:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.set_thumbnail(url=msg.content)

                elif value == "Image":
                    await ctx.send("Enter the **Image URL**:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.set_image(url=msg.content)

                elif value == "Footer Text":
                    await ctx.send("Enter the **Footer Text**:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.set_footer(text=msg.content, icon_url=embed.footer.icon_url)

                elif value == "Footer Icon":
                    await ctx.send("Enter the **Footer Icon URL**:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.set_footer(text=embed.footer.text or "", icon_url=msg.content)

                elif value == "Author Text":
                    await ctx.send("Enter the **Author Text**:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.set_author(name=msg.content, icon_url=embed.author.icon_url)

                elif value == "Author Icon":
                    await ctx.send("Enter the **Author Icon URL**:")
                    msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.set_author(name=embed.author.name or "", icon_url=msg.content)

                elif value == "Add Field":
                    await ctx.send("Enter **Field Title**:")
                    name = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    await ctx.send("Enter **Field Value**:")
                    val = await ctx.bot.wait_for("message", timeout=60, check=chk)
                    embed.add_field(name=name.content, value=val.content, inline=False)

                await msg_embed.edit(embed=embed)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timeout! Please try again.")

        # --- Send Embed Callback ---
        async def send_callback(interaction):
            if interaction.user.id != interaction_user.id:
                await interaction.response.send_message("This menu is not yours!", ephemeral=True)
                return

            await interaction.response.defer()
            await ctx.send("Mention the **channel** to send the embed (e.g., #general):")
            try:
                ch_msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                if ch_msg.channel_mentions:
                    channel = ch_msg.channel_mentions[0]
                else:
                    await ctx.send("❌ You must mention a valid channel.")
                    return

                await ctx.send("Type any **role/user mentions** you want above the embed, or 'none':")
                mention_msg = await ctx.bot.wait_for("message", timeout=60, check=chk)
                mentions_text = mention_msg.content if mention_msg.content.lower() != "none" else ""

                await channel.send(content=mentions_text, embed=embed)
                await ctx.send("✅ Embed sent successfully!")

            except asyncio.TimeoutError:
                await ctx.send("⏰ Timeout! Please try again.")

        # --- Cancel Callback ---
        async def cancel_callback(interaction):
            if interaction.user.id != interaction_user.id:
                await interaction.response.send_message("This menu is not yours!", ephemeral=True)
                return
            await interaction.response.defer()
            await msg_embed.delete()
            await ctx.send("❌ Embed setup canceled.")

        # --- UI Components ---
        select = Select(
            placeholder="Select an option to edit",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Title"),
                discord.SelectOption(label="Description"),
                discord.SelectOption(label="Add Field"),
                discord.SelectOption(label="Color"),
                discord.SelectOption(label="Thumbnail"),
                discord.SelectOption(label="Image"),
                discord.SelectOption(label="Footer Text"),
                discord.SelectOption(label="Footer Icon"),
                discord.SelectOption(label="Author Text"),
                discord.SelectOption(label="Author Icon"),
            ]
        )
        select.callback = select_callback

        button_send = Button(label="Send Embed", style=discord.ButtonStyle.success)
        button_send.callback = send_callback

        button_cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        button_cancel.callback = cancel_callback

        view = View(timeout=300)
        view.add_item(select)
        view.add_item(button_send)
        view.add_item(button_cancel)

        msg_embed = await ctx.send(embed=embed, content="Embed Builder Active! Use the menu to edit.", view=view)

async def setup(bot):
    await bot.add_cog(Embed(bot))
