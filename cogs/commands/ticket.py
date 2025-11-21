# ticket_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import io
from typing import List, Optional

# -----------------------------
# Config & Defaults
# -----------------------------
JSON_FILE = "tickets.json"
DEFAULT_COLOR = 0xEA0A37
DEFAULT_EMBED = {
    "title": "🎫 Need Help? We're Here for You!",
    "description": (
        "If you're experiencing an issue, need support, or want to talk to the team privately, you can open a confidential support ticket by clicking the button below.\n\n"
        "🛡️ Your privacy is our priority – only you and our support team will be able to view the conversation inside your ticket.\n\n"
        "✅ Use this system for:\n"
        "• Questions or general help\n"
        "• Reporting issues or bugs\n"
        "• Private conversations with staff\n"
        "• Any other support-related needs\n\n"
        "📌 To open a ticket, simply click the Create Ticket button below. A private channel will be created just for you.\n\n"
        "📝 Once your ticket is open, please explain your situation clearly so we can help you as fast and efficiently as possible."
    ),
    "image": "https://cdn.discordapp.com/attachments/1312336278368292928/1312358193967665162/download-2024-08-19T210821.492.jpeg"
}

# -----------------------------
# JSON Storage
# -----------------------------
def load_json():
    if not os.path.exists(JSON_FILE):
        data = {"panels": [], "tickets": [], "ticket_counter": {}}
        save_json(data)
    else:
        with open(JSON_FILE, "r") as f:
            data = json.load(f)
    return data

def save_json(data):
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# Ticket Views
# -----------------------------
class TicketView(discord.ui.View):
    def __init__(self, bot: commands.Bot, staff_roles: Optional[List[int]] = None, transcript_channel: Optional[int] = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.staff_roles = staff_roles or []
        self.transcript_channel = transcript_channel

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.primary, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"{interaction.user.mention} claimed this ticket.", ephemeral=True)

    @discord.ui.button(label="❌ Close", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        data = load_json()
        ticket = next((t for t in data["tickets"] if t["channel_id"] == interaction.channel.id), None)
        if ticket:
            # Collect transcript
            messages = []
            async for msg in interaction.channel.history(limit=None, oldest_first=True):
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                messages.append(f"[{timestamp}] {msg.author}: {msg.content}")
            transcript_text = "\n".join(messages)

            # DM user
            user = interaction.guild.get_member(ticket["creator_id"])
            if user:
                try:
                    await user.send(
                        embed=discord.Embed(
                            title=f"📄 Ticket Transcript: {interaction.channel.name}",
                            description="Here is the transcript of your ticket.",
                            color=DEFAULT_COLOR
                        ).add_field(name="Transcript", value=f"```{transcript_text}```")
                    )
                except Exception:
                    pass

            # Send transcript to staff transcript channel
            if self.transcript_channel:
                staff_channel = interaction.guild.get_channel(self.transcript_channel)
                if staff_channel:
                    staff_mentions = " ".join([f"<@&{r_id}>" for r_id in self.staff_roles])
                    file = discord.File(io.StringIO(transcript_text), filename=f"{interaction.channel.name}.txt")
                    await staff_channel.send(content=f"Ticket `{interaction.channel.name}` closed by {interaction.user.mention}\n{staff_mentions}", file=file)

            # Remove ticket from JSON
            data["tickets"].remove(ticket)
            save_json(data)

        await interaction.channel.delete(reason="Ticket closed")

class CreateTicketButton(discord.ui.View):
    def __init__(self, bot: commands.Bot, panel_id: int, staff_roles: Optional[List[int]] = None, transcript_channel: Optional[int] = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.panel_id = panel_id
        self.staff_roles = staff_roles or []
        self.transcript_channel = transcript_channel

    @discord.ui.button(label="🎟️ Create Ticket", style=discord.ButtonStyle.primary, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_json()
        panel = next((p for p in data["panels"] if p["message_id"] == self.panel_id), None)
        if not panel:
            await interaction.response.send_message("❌ Panel not found.", ephemeral=True)
            return

        # Check for existing ticket
        user_ticket = next((t for t in data["tickets"] if t["guild_id"] == interaction.guild.id and t["creator_id"] == interaction.user.id), None)
        if user_ticket:
            channel = interaction.guild.get_channel(user_ticket["channel_id"])
            if channel:
                await interaction.response.send_message(f"❌ You already have a ticket: {channel.mention}", ephemeral=True)
                return
            else:
                data["tickets"].remove(user_ticket)
                save_json(data)

        # Increment ticket counter
        guild_id = interaction.guild.id
        counter = data.get("ticket_counter", {}).get(str(guild_id), 0) + 1
        data.setdefault("ticket_counter", {})[str(guild_id)] = counter

        # Create overwrites
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }

        for r_id in self.staff_roles:
            role = interaction.guild.get_role(r_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # Create ticket channel
        channel_name = f"ticket-{counter}"
        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            reason=f"Ticket created by {interaction.user}"
        )

        # Save ticket in JSON
        ticket_data = {
            "guild_id": guild_id,
            "channel_id": ticket_channel.id,
            "creator_id": interaction.user.id,
            "option_label": "General",
            "staff_role": self.staff_roles,
            "open": True,
            "staff_transcript_channel": self.transcript_channel
        }
        data["tickets"].append(ticket_data)
        save_json(data)

        # Send **custom welcome embed** + mention user and staff roles
        mentions = f"{interaction.user.mention}"
        if self.staff_roles:
            mentions += " " + " ".join([f"<@&{r_id}>" for r_id in self.staff_roles])

        embed = discord.Embed(
            title="🎫 Your Ticket is Open!",
            description=(
                f"{interaction.user.mention}, welcome! Your ticket has been created.\n\n"
                "🛡️ **Your data is safe and confidential** — only you and the assigned staff can see this conversation.\n"
                "✅ Our support team will assist you as soon as possible.\n\n"
                "Use the buttons below to **claim** or **close** the ticket when your issue is resolved."
            ),
            color=DEFAULT_COLOR
        )
        if self.staff_roles:
            staff_mentions = " ".join([f"<@&{r_id}>" for r_id in self.staff_roles])
            embed.add_field(name="Staff on Duty", value=staff_mentions, inline=False)

        view = TicketView(self.bot, staff_roles=self.staff_roles, transcript_channel=self.transcript_channel)
        await ticket_channel.send(content=mentions, embed=embed, view=view)
        await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)

# -----------------------------
# Ticket Cog
# -----------------------------
class TicketSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not os.path.exists(JSON_FILE):
            save_json({"panels": [], "tickets": [], "ticket_counter": {}})

    async def cog_load(self):
        try:
            self.bot.add_view(TicketView(self.bot))
            data = load_json()
            for panel in data.get("panels", []):
                self.bot.add_view(CreateTicketButton(
                    self.bot,
                    panel["message_id"],
                    staff_roles=[r for o in panel["options"] for r in (o.get("staff_role") or [])],
                    transcript_channel=panel.get("transcript_channel")
                ))
        except Exception:
            pass

    @app_commands.command(name="ticketsetup", description="Send the main ticket panel")
    async def ticketsetup(self, interaction: discord.Interaction):
        modal = StaffRoleModal(bot=self.bot, channel=interaction.channel)
        await interaction.response.send_modal(modal)

# -----------------------------
# Modal for staff roles + transcript channel
# -----------------------------
class StaffRoleModal(discord.ui.Modal, title="Setup Ticket Staff Roles"):
    staff_roles_input = discord.ui.TextInput(
        label="Staff Role IDs (comma-separated)",
        placeholder="123456789012345678, 987654321098765432",
        required=False
    )
    transcript_channel_input = discord.ui.TextInput(
        label="Transcript Channel ID",
        placeholder="123456789012345678",
        required=True
    )

    def __init__(self, bot: commands.Bot, channel: discord.TextChannel):
        super().__init__()
        self.bot = bot
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        staff_roles = [int(r.strip()) for r in self.staff_roles_input.value.split(",") if r.strip().isdigit()]
        transcript_channel = int(self.transcript_channel_input.value.strip())
        embed = discord.Embed(
            title=DEFAULT_EMBED["title"],
            description=DEFAULT_EMBED["description"],
            color=DEFAULT_COLOR
        )
        embed.set_image(url=DEFAULT_EMBED["image"])
        view = CreateTicketButton(self.bot, panel_id=0, staff_roles=staff_roles, transcript_channel=transcript_channel)
        msg = await self.channel.send(embed=embed, view=view)

        # Save panel in JSON
        data = load_json()
        panel_data = {
            "guild_id": interaction.guild.id,
            "channel_id": self.channel.id,
            "message_id": msg.id,
            "embed": DEFAULT_EMBED,
            "options": [{"label": "General", "staff_role": staff_roles}],
            "transcript_channel": transcript_channel
        }
        data["panels"].append(panel_data)
        save_json(data)

        view.panel_id = msg.id
        self.bot.add_view(view)
        await interaction.response.send_message("✅ Ticket panel sent with staff roles and transcript channel!", ephemeral=True)

# -----------------------------
# Setup
# -----------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystem(bot))
