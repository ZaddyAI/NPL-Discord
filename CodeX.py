import os
import subprocess
import asyncio
import traceback
from threading import Thread
from datetime import datetime

import aiohttp
import discord
from discord.ext import commands

from core import Context
from core.Cog import Cog
from core.axon import axon
from utils.Tools import *
from utils.config import *

import jishaku
import cogs

os.environ["JISHAKU_NO_DM_TRACEBACK"] = "False"
os.environ["JISHAKU_HIDE"] = "True"
os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
os.environ["JISHAKU_FORCE_PAGINATOR"] = "True"

from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("TOKEN")

# --- AUTO GIT PULL ---
GIT_REPO_PATH = "/home/container"  # Path where repo is cloned
GIT_BRANCH = "main"  # Branch to pull from

try:
    print("Pulling latest code from GitHub...")
    # First check if we're in a git repository
    result = subprocess.run(["git", "status"], cwd=GIT_REPO_PATH, capture_output=True, text=True)
    if result.returncode == 0:
        subprocess.run(["git", "fetch", "--all"], cwd=GIT_REPO_PATH, check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{GIT_BRANCH}"], cwd=GIT_REPO_PATH, check=True)
        print("Git pull successful!")
    else:
        print("Not a git repository, skipping git pull...")
except Exception as e:
    print(f"Failed to pull latest code: {e}")
    print("Continuing with existing code...")
# --- END GIT PULL ---

client = axon()
tree = client.tree

@client.event
async def on_ready():
    print("""
        \033[1;31m

        ███╗   ██╗██████╗ ██╗
        ████╗  ██║██╔══██╗██║
        ██╔██╗ ██║██████╔╝██║
        ██║╚██╗██║██╔═══╝ ██║
        ██║ ╚████║██║     ███████╗
        ╚═╝  ╚═══╝╚═╝     ╚══════╝

        \033[0m
    """)
    print("Loaded & Online!")
    print(f"Logged in as: {client.user}")
    print(f"Connected to: {len(client.guilds)} guilds")
    print(f"Connected to: {len(client.users)} users")
    try:
        synced = await client.tree.sync()
        all_commands = list(client.commands)
        print(f"Synced Total {len(all_commands)} Client Commands and {len(synced)} Slash Commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@client.event
async def on_command_completion(context: commands.Context) -> None:
    if context.author.id == 767979794411028491:
        return
    full_command_name = context.command.qualified_name
    split = full_command_name.split("\n")
    executed_command = str(split[0])
    webhook_url = "https://discord.com/api/webhooks/1411962458855182386/ZV5GX05CkAGsP9xtapg5yrzbIbDDdUbbtCdjkdIGIKmq0d_LlWp35R3Ct375JDBza9sL"
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        if context.guild is not None:
            try:
                embed = discord.Embed(color=0x000000)
                avatar_url = context.author.avatar.url if context.author.avatar else context.author.default_avatar.url
                embed.set_author(
                    name=f"Executed {executed_command} Command By : {context.author}",
                    icon_url=avatar_url
                )
                embed.set_thumbnail(url=avatar_url)
                embed.add_field(name=" Command Name :",
                                value=f"{executed_command}",
                                inline=False)
                embed.add_field(
                    name=" Command Executed By :",
                    value=f"{context.author} | ID: [{context.author.id}](https://discord.com/users/{context.author.id})",
                    inline=False)
                embed.add_field(
                    name=" Command Executed In :",
                    value=f"{context.guild.name} | ID: [{context.guild.id}](https://discord.com/guilds/{context.guild.id})",
                    inline=False)
                embed.add_field(
                    name=" Command Executed In Channel :",
                    value=f"{context.channel.name} | ID: [{context.channel.id}](https://discord.com/channels/{context.guild.id}/{context.channel.id})",
                    inline=False)
                embed.timestamp = discord.utils.utcnow()
                embed.set_footer(text="Zaddy",
                                 icon_url=client.user.display_avatar.url)
                await webhook.send(embed=embed)
            except Exception as e:
                print(f'Command failed: {e}')
                traceback.print_exc()
        else:
            try:
                embed1 = discord.Embed(color=0x000000)
                avatar_url = context.author.avatar.url if context.author.avatar else context.author.default_avatar.url
                embed1.set_author(
                    name=f"Executed {executed_command} Command By : {context.author}",
                    icon_url=avatar_url
                )
                embed1.set_thumbnail(url=avatar_url)
                embed1.add_field(name=" Command Name :",
                                 value=f"{executed_command}",
                                 inline=False)
                embed1.add_field(
                    name=" Command Executed By :",
                    value=f"{context.author} | ID: [{context.author.id}](https://discord.com/users/{context.author.id})",
                    inline=False)
                embed1.set_footer(text=f"Zaddy",
                                  icon_url=client.user.display_avatar.url)
                await webhook.send(embed=embed1)
            except Exception as e:
                print(f'Command failed: {e}')
                traceback.print_exc()

from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Zaddy Bot is Running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    server = Thread(target=run)
    server.start()

keep_alive()

async def main():
    async with client:
        # Install requirements first
        try:
            print("Installing requirements...")
            subprocess.run(["pip", "install", "-r", "requirements.txt"], check=True)
        except Exception as e:
            print(f"Failed to install requirements: {e}")

        # Clear screen
        os.system("clear")

        # Load jishaku
        await client.load_extension("jishaku")

        # Start the bot
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
