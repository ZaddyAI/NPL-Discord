import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import io

DEFAULT_COLOR = 0xea0a37
ticket_counter = 0

# ─────────────────────────────
# Embed Editor Modal
# ─────────────────────────────
class EmbedEditModal(discord.ui.Modal, title="Edit Ticket Embed"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.title_input = discord.ui.TextInput(label="Embed Title", required=False, placeholder="Ticket Support")
        self.desc_input = discord.ui.TextInput(label="Embed Description", style=discord.TextStyle.paragraph, required=False, placeholder="Choose an option below to open a ticket.")
        self.image_input = discord.ui.TextInput(label="Embed Image URL", required=False, placeholder="https://example.com/banner.png")
        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=self.title_input.value or "Support Ticket",
            description=self.desc_input.value or "Select an option below to open a ticket.",
            color=DEFAULT_COLOR
        )
        if self.image_input.value:
            embed.set_image(url=self.image_input.value)
        self.view.embed = embed
        await interaction.response.edit_message(embed=embed, view=self.view)


# ─────────────────────────────
# Add Ticket Option Modal
# ─────────────────────────────
class AddOptionModal(discord.ui.Modal, title="Add Ticket Option"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.option_name = discord.ui.TextInput(label="Option Name", required=True, placeholder="e.g. Billing Support")
        self.emoji_input = discord.ui.TextInput(label="Emoji (type emoji or custom ID)", required=False, placeholder="😎 or <:custom:123456789>")
        self.add_item(self.option_name)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction):
        emoji_val = None
        if self.emoji_input.value:
            try:
                emoji_val = discord.PartialEmoji.from_str(self.emoji_input.value)
            except:
                emoji_val = None

        # Role dropdown
        role_options = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
            if not role.is_default()
        ]
        role_select = discord.ui.Select(
            placeholder="Select staff role for this option",
            options=role_options[:25]
        )

        async def role_callback(i2: discord.Interaction):
            staff_role_id = int(i2.data["values"][0])
            self.view.options.append({
                "label": self.option_name.value,
                "emoji": emoji_val,
                "staff_role": staff_role_id
            })
            await i2.response.edit_message(content=f"✅ Added option `{self.option_name.value}`", view=self.view)

        role_select.callback = role_callback
        v = discord.ui.View()
        v.add_item(role_select)
        await interaction.response.edit_message(content="Select staff role:", view=v)


# ─────────────────────────────
# Ticket Setup Main View
# ─────────────────────────────
class TicketSetupView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=300)
        self.bot = bot
        self.author = author
        self.embed = discord.Embed(
            title="Ticket Panel",
            description="Select an option to open a ticket.",
            color=DEFAULT_COLOR
        )
        self.options = []
        self.channel = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    @discord.ui.select(
        placeholder="Select setup action",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Edit Embed", value="embed_edit", emoji="📝"),
            discord.SelectOption(label="Add Ticket Option", value="add_option", emoji="➕"),
            discord.SelectOption(label="Set Channel", value="set_channel", emoji="📺"),
            discord.SelectOption(label="Send Panel", value="send_panel", emoji="📨"),
        ]
    )
    async def menu(self, interaction: discord.Interaction, select: discord.ui.Select):
        value = select.values[0]

        if value == "embed_edit":
            await interaction.response.send_modal(EmbedEditModal(self))

        elif value == "add_option":
            await interaction.response.send_modal(AddOptionModal(self))

        elif value == "set_channel":
            await interaction.response.send_message(
                "Type the channel ID or mention where the ticket panel should be sent.", ephemeral=True
            )

            def check(m):
                return m.author.id == interaction.user.id and m.channel == interaction.channel

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=60)
                # Parse channel ID from mention or raw ID
                channel_id = None
                if msg.channel_mentions:
                    channel_id = msg.channel_mentions[0].id
                else:
                    try:
                        channel_id = int(msg.content.strip("<># "))
                    except:
                        pass

                channel = interaction.guild.get_channel(channel_id)
                if not channel or not isinstance(channel, discord.TextChannel):
                    await interaction.followup.send("❌ Invalid channel ID.", ephemeral=True)
                    return

                self.channel = channel
                await interaction.followup.send(f"✅ Channel set to {self.channel.mention}", ephemeral=True)

            except asyncio.TimeoutError:
                await interaction.followup.send("❌ Timeout. Please try again.", ephemeral=True)

        elif value == "send_panel":
            await self.send_panel(interaction)

    async def send_panel(self, interaction: discord.Interaction):
        global ticket_counter
        if not self.channel:
            await interaction.response.send_message("❌ Please set a channel first.", ephemeral=True)
            return
        if not self.options:
            await interaction.response.send_message("❌ Please add at least one ticket option.", ephemeral=True)
            return

        select = discord.ui.Select(
            placeholder="Select ticket type",
            options=[
                discord.SelectOption(label=o["label"], value=o["label"], emoji=o["emoji"])
                if o["emoji"] else discord.SelectOption(label=o["label"], value=o["label"])
                for o in self.options
            ]
        )

        async def ticket_callback(i: discord.Interaction):
            global ticket_counter
            label = i.data["values"][0]
            option = next((opt for opt in self.options if opt["label"] == label), None)
            if not option:
                await i.response.send_message("❌ Option not found.", ephemeral=True)
                return

            staff_role = i.guild.get_role(option["staff_role"])
            ticket_counter += 1
            overwrites = {
                i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            }
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

            ticket_channel = await i.guild.create_text_channel(
                name=f"{label.lower()}-{ticket_counter}",
                overwrites=overwrites,
                reason="New Support Ticket"
            )

            ticket_embed = discord.Embed(
                title=f"{label} Ticket",
                description=f"{i.user.mention} opened a ticket. {staff_role.mention if staff_role else ''}",
                color=DEFAULT_COLOR
            )

            view = TicketView(i.user)
            await ticket_channel.send(content=f"{i.user.mention} {staff_role.mention if staff_role else ''}", embed=ticket_embed, view=view)
            await i.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)

        select.callback = ticket_callback
        v = discord.ui.View()
        v.add_item(select)
        await self.channel.send(embed=self.embed, view=v)
        await interaction.response.send_message("✅ Ticket panel sent successfully!", ephemeral=True)


# ─────────────────────────────
# Ticket Interaction Views
# ─────────────────────────────
class TicketView(discord.ui.View):
    def __init__(self, creator):
        super().__init__(timeout=None)
        self.creator = creator
        self.claimed = False

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.primary)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            await interaction.response.send_message("Ticket already claimed.", ephemeral=True)
        else:
            self.claimed = True
            await interaction.channel.send(f"{interaction.user.mention} claimed this ticket.")
            await interaction.response.defer()

    @discord.ui.button(label="❌ Close", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choose an action:", view=CloseOptionsView(interaction.channel, self.creator), ephemeral=True)


class CloseOptionsView(discord.ui.View):
    def __init__(self, channel, creator):
        super().__init__()
        self.channel = channel
        self.creator = creator

    @discord.ui.button(label="📄 Transcript", style=discord.ButtonStyle.secondary)
    async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        messages = [f"{msg.created_at:%Y-%m-%d %H:%M:%S} - {msg.author}: {msg.content}" async for msg in self.channel.history(limit=None, oldest_first=True)]
        transcript_file = discord.File(io.BytesIO("\n".join(messages).encode()), filename=f"transcript-{self.channel.name}.txt")
        await interaction.user.send("📄 Transcript:", file=transcript_file)
        await interaction.response.send_message("Transcript sent to your DMs.", ephemeral=True)

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Deleting channel...", ephemeral=True)
        await self.channel.delete(reason="Ticket closed")


# ─────────────────────────────
# Cog Setup
# ─────────────────────────────
class TicketSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ticketsetup", description="Create and configure a custom ticket panel")
    async def ticketsetup(self, interaction: discord.Interaction):
        view = TicketSetupView(self.bot, interaction.user)
        await interaction.response.send_message(embed=view.embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(TicketSystem(bot))