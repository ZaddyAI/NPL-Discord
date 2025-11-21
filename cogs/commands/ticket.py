# ticket_system.py
import discord
from discord.ext import commands
from discord import app_commands
import json
import os
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
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="📌 Claim", style=discord.ButtonStyle.primary, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"{interaction.user.mention} claimed this ticket.", ephemeral=True)

    @discord.ui.button(label="❌ Close", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        data = load_json()
        ticket = next((t for t in data["tickets"] if t["channel_id"] == interaction.channel.id), None)
        if ticket:
            # Remove ticket from JSON
            data["tickets"].remove(ticket)
            save_json(data)
        await interaction.channel.delete(reason="Ticket closed")

class CreateTicketButton(discord.ui.View):
    def __init__(self, bot: commands.Bot, panel_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.panel_id = panel_id

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.success, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_json()
        panel = next((p for p in data["panels"] if p["message_id"] == self.panel_id), None)
        if not panel:
            await interaction.response.send_message("❌ Panel not found.", ephemeral=True)
            return

        # Check if user already has a ticket
        user_ticket = next((t for t in data["tickets"] if t["guild_id"] == interaction.guild.id and t["creator_id"] == interaction.user.id), None)
        if user_ticket:
            channel = interaction.guild.get_channel(user_ticket["channel_id"])
            if channel:
                await interaction.response.send_message(f"❌ You already have a ticket: {channel.mention}", ephemeral=True)
                return
            else:
                # stale entry
                data["tickets"].remove(user_ticket)
                save_json(data)

        # Increment ticket counter
        guild_id = interaction.guild.id
        counter = data.get("ticket_counter", {}).get(str(guild_id), 0) + 1
        data.setdefault("ticket_counter", {})[str(guild_id)] = counter

        # Create ticket channel
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }

        # Allow all staff roles to see the ticket
        for option in panel["options"]:
            staff_roles = option.get("staff_role", [])
            if isinstance(staff_roles, list):
                for r_id in staff_roles:
                    role = interaction.guild.get_role(r_id)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            elif staff_roles:
                role = interaction.guild.get_role(staff_roles)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

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
            "staff_role": [r for o in panel["options"] for r in (o.get("staff_role") or [])],
            "open": True
        }
        data["tickets"].append(ticket_data)
        save_json(data)

        # Send ticket message
        embed = discord.Embed(title="Your Ticket", description="Ticket channel created. Use the buttons below to claim or close.", color=DEFAULT_COLOR)
        view = TicketView(self.bot)
        await ticket_channel.send(content=interaction.user.mention, embed=embed, view=view)
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
        # Register persistent views
        try:
            self.bot.add_view(TicketView(self.bot))
            # Register all panel buttons from JSON
            data = load_json()
            for panel in data.get("panels", []):
                self.bot.add_view(CreateTicketButton(self.bot, panel["message_id"]))
        except Exception:
            pass

    @app_commands.command(name="ticketsetup", description="Send the main ticket panel")
    async def ticketsetup(self, interaction: discord.Interaction):
        # Use your default embed
        embed = discord.Embed(
            title=DEFAULT_EMBED["title"],
            description=DEFAULT_EMBED["description"],
            color=DEFAULT_COLOR
        )
        embed.set_image(url=DEFAULT_EMBED["image"])

        # Send panel in the current channel
        view = CreateTicketButton(self.bot, panel_id=0)
        msg = await interaction.channel.send(embed=embed, view=view)

        # Save panel in JSON
        data = load_json()
        panel_data = {
            "guild_id": interaction.guild.id,
            "channel_id": interaction.channel.id,
            "message_id": msg.id,
            "embed": DEFAULT_EMBED,
            "options": [{"label": "General", "staff_role": []}]
        }
        data["panels"].append(panel_data)
        save_json(data)

        # Update view with correct panel_id
        view.panel_id = msg.id
        self.bot.add_view(view)
        await interaction.response.send_message("✅ Ticket panel sent.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystem(bot))
