import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import aiohttp
import os
import asyncio
import feedparser
from datetime import datetime
import re
import random
import json
from utils.Tools import *

db_folder = 'db'
db_file = 'social_feed.db'
db_path = os.path.join(db_folder, db_file)

# Nepal flag blue color
NEPAL_BLUE = 0x003893
TWITTER_BLUE = 0x1DA1F2
YOUTUBE_RED = 0xFF0000
REDDIT_ORANGE = 0xFF5700

# Real social media icons
TWITTER_ICON = "https://abs.twimg.com/favicons/twitter.2.ico"
YOUTUBE_ICON = "https://www.youtube.com/s/desktop/5c6daf13/img/favicon_144x144.png"
REDDIT_ICON = "https://www.redditstatic.com/icon.png"
DISCORD_ICON = "https://assets-global.website-files.com/6257adef93867e50d84d30e2/636e0a6a49cf127bf92de1e2_icon_clyde_blurple_RGB.png"

async def init_db():
    if not os.path.exists(db_folder):
        os.makedirs(db_folder)
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DROP TABLE IF EXISTS SocialFeed')
        await db.execute('''CREATE TABLE IF NOT EXISTS SocialFeed (
                                guild_id INTEGER,
                                channel_id INTEGER,
                                platform TEXT,
                                feed_name TEXT,
                                feed_url TEXT,
                                last_post_id TEXT,
                                last_post_time TIMESTAMP,
                                last_check_time TIMESTAMP,
                                working_instance TEXT,
                                service_type TEXT,
                                mention_text TEXT,
                                display_name TEXT,
                                channel_data TEXT,
                                PRIMARY KEY (guild_id, feed_name)
                            )''')
        await db.commit()

class RoleAutocomplete(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=60)
        self.interaction = interaction
        self.selected_roles = []

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select roles to mention (optional)...",
        min_values=0,
        max_values=10
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_roles = select.values
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Skip Roles", style=discord.ButtonStyle.gray)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected_roles = []
        await interaction.response.defer()
        self.stop()

class WatchButton(discord.ui.View):
    def __init__(self, video_url: str, platform: str, direct_video_url: str = None):
        super().__init__(timeout=None)
        self.video_url = video_url
        self.platform = platform
        self.direct_video_url = direct_video_url

        # Create button based on platform
        if platform == "youtube":
            button_label = "📺 Watch on YouTube"
            button_style = discord.ButtonStyle.red
            self.add_item(discord.ui.Button(
                label=button_label,
                style=button_style,
                url=video_url
            ))
        elif platform == "twitter":
            button_label = "🐦 View on Twitter"
            button_style = discord.ButtonStyle.blurple
            self.add_item(discord.ui.Button(
                label=button_label,
                style=button_style,
                url=video_url
            ))
        elif platform == "reddit":
            button_label = "🤖 View on Reddit"
            button_style = discord.ButtonStyle.green
            self.add_item(discord.ui.Button(
                label=button_label,
                style=button_style,
                url=video_url
            ))
        else:
            button_label = "🔗 View Post"
            button_style = discord.ButtonStyle.gray
            self.add_item(discord.ui.Button(
                label=button_label,
                style=button_style,
                url=video_url
            ))

        # Add direct video play button if available
        if direct_video_url:
            self.add_item(discord.ui.Button(
                label="🎬 Play Video",
                style=discord.ButtonStyle.blurple,
                url=direct_video_url
            ))

class PlatformDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Twitter/X",
                value="twitter",
                emoji="🐦",
                description="Follow Twitter/X accounts"
            ),
            discord.SelectOption(
                label="YouTube",
                value="youtube",
                emoji="📺",
                description="Subscribe to YouTube channels"
            ),
            discord.SelectOption(
                label="Reddit",
                value="reddit",
                emoji="🤖",
                description="Follow subreddits and users"
            ),
        ]
        super().__init__(placeholder="🔍 Select a platform...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.view.platform = self.values[0]
        await interaction.response.send_modal(AddFeedModal(self.view))

class AddFeedModal(discord.ui.Modal, title="Add Social Feed"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.timeout = 300

    username = discord.ui.TextInput(
        label="Username / Channel Name / Subreddit",
        placeholder="e.g., CricketNep, @FarahKhanK, r/nepal",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.view.feed_name = self.username.value.strip()

        # Show role selection
        role_view = RoleAutocomplete(interaction)
        embed = discord.Embed(
            title="🔔 Role Selection (Optional)",
            description="Select roles to mention when new posts arrive.\n\n• Click **Confirm** to save with selected roles\n• Click **Skip Roles** to continue without mentions",
            color=NEPAL_BLUE
        )
        await interaction.followup.send(embed=embed, view=role_view, ephemeral=True)

        # Wait for role selection
        await role_view.wait()

        if role_view.selected_roles:
            role_mentions = " ".join([role.mention for role in role_view.selected_roles])
            self.view.mention_text = role_mentions

        await self.view.finalize(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        embed = discord.Embed(
            title="❌ Modal Error",
            description="An error occurred while processing your request.",
            color=0xff0000
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

class SocialFeedView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot
        self.platform = None
        self.feed_name = None
        self.mention_text = None
        self.add_item(PlatformDropdown())

    async def on_timeout(self):
        pass

    def get_chromium_headers(self):
        """Get realistic Chromium browser headers to avoid detection"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        ]

        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

    def get_twitter_services(self):
        """Get list of WORKING Twitter service alternatives with all instances"""
        return {
            "nitter": {
                "instances": [
                    "https://xcancel.com",
                    "https://nitter.privacyredirect.com",
                    "https://nitter.poast.org",
                    "https://nuku.trabun.org",
                    "https://nitter.space",
                    "https://lightbrd.com",
                    "https://nitter.net",
                    "https://nitter.tiekoetter.com",
                    "https://nitter.weiler.rocks",
                    "https://nitter.privacydev.net"
                ],
                "url_template": "{instance}/{username}/rss",
                "name": "Nitter",
                "emoji": "🔵",
                "description": "Privacy-focused Twitter frontend"
            },
            "rsshub": {
                "instances": [
                    "https://rsshub.app",
                    "https://rsshub.rssforever.com",
                ],
                "url_template": "{instance}/twitter/user/{username}",
                "name": "RSSHub",
                "emoji": "🔗",
                "description": "Universal RSS generator"
            }
        }

    def get_reddit_services(self):
        """Get list of Reddit service alternatives"""
        return {
            "reddit": {
                "instances": [
                    "https://www.reddit.com",
                    "https://old.reddit.com"
                ],
                "url_template": "{instance}/{feed_name}/.rss",
                "name": "Reddit",
                "emoji": "🟠",
                "description": "Direct Reddit RSS"
            },
            "rsshub": {
                "instances": [
                    "https://rsshub.app",
                    "https://rsshub.rssforever.com"
                ],
                "url_template": "{instance}/reddit/{feed_name}",
                "name": "RSSHub",
                "emoji": "🔗",
                "description": "Universal RSS generator"
            }
        }

    def create_twitter_error_embed(self, feed_name):
        """Create attractive Twitter error embed"""
        embed = discord.Embed(
            title="Twitter/X Feed Error",
            color=TWITTER_BLUE,
            timestamp=datetime.utcnow()
        )

        embed.set_thumbnail(url=TWITTER_ICON)

        embed.add_field(
            name="❌ Service Unavailable",
            value=f"All Twitter/X services are currently unavailable for `{feed_name}`.",
            inline=False
        )

        embed.add_field(
            name="🔄 What's Happening?",
            value="Twitter has restricted access to their RSS feeds. Most alternative services are currently down or blocked.",
            inline=False
        )

        embed.add_field(
            name="💡 What to Do?",
            value="• Try using YouTube or Reddit feeds instead\n• Twitter feeds may work intermittently\n• Check back later as services may recover",
            inline=False
        )

        embed.set_footer(text="🔄 Auto-retrying every 60 seconds • Powered by NPL Utils", icon_url=DISCORD_ICON)
        return embed

    def clean_html_content(self, html_content):
        """Clean HTML content from RSS feed descriptions"""
        if not html_content:
            return ""

        # Remove CDATA wrapper if present
        if html_content.startswith('<![CDATA[') and html_content.endswith(']]>'):
            html_content = html_content[9:-3]

        # Remove HTML tags but keep text content
        clean_text = re.sub('<[^<]+?>', '', html_content)

        # Clean up extra whitespace
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        return clean_text

    def extract_image_urls_from_description(self, description):
        """Extract image URLs from RSS feed description"""
        if not description:
            return []

        # Look for img tags in the description
        img_pattern = r'<img[^>]+src="([^"]+)"'
        image_urls = re.findall(img_pattern, description)

        return image_urls

    async def get_youtube_channel_info(self, channel_id):
        """Get YouTube channel name and thumbnail using Invidious API"""
        invidious_instances = [
            "vid.puffyan.us",
            "invidious.fdn.fr",
            "yewtu.be"
        ]

        for instance in invidious_instances:
            try:
                url = f"https://{instance}/api/v1/channels/{channel_id}"
                async with aiohttp.ClientSession(headers=self.get_chromium_headers()) as session:
                    async with session.get(url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            return {
                                'name': data.get('author', 'Unknown Channel'),
                                'thumbnail': data.get('authorThumbnails', [{}])[-1].get('url', ''),
                                'description': data.get('description', '')
                            }
            except Exception:
                continue

        return None

    async def resolve_youtube_identifier(self, identifier):
        """Resolve YouTube username/handle to channel ID"""
        if identifier.startswith('@'):
            # This is a YouTube handle
            handle = identifier.lstrip('@')

            # Try to get channel ID from handle using Invidious
            invidious_instances = ["vid.puffyan.us", "invidious.fdn.fr"]

            for instance in invidious_instances:
                try:
                    url = f"https://{instance}/api/v1/channels/{handle}"
                    async with aiohttp.ClientSession(headers=self.get_chromium_headers()) as session:
                        async with session.get(url, timeout=10) as response:
                            if response.status == 200:
                                data = await response.json()
                                if data.get('authorId'):
                                    return data['authorId'], data.get('author', handle)
                except:
                    continue

        # If it's already a channel ID
        if re.match(r'^UC[\w-]{22}$', identifier):
            return identifier, f"Channel {identifier}"

        return None, identifier

    def generate_feed_url(self, platform, feed_name, service_type=None, instance=None):
        """Generate appropriate RSS feed URL based on platform"""
        if platform == "twitter":
            clean_name = feed_name.lstrip('@')
            services = self.get_twitter_services()

            if service_type and instance:
                service = services.get(service_type)
                if service:
                    return service["url_template"].format(instance=instance, username=clean_name)

            # Try Nitter first with random instance
            service = services["nitter"]
            instance = random.choice(service["instances"])
            return service["url_template"].format(instance=instance, username=clean_name)

        elif platform == "youtube":
            # For YouTube, use the channel ID directly
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={feed_name}"

        elif platform == "reddit":
            clean_name = feed_name.lower().strip()
            services = self.get_reddit_services()

            if service_type and instance:
                service = services.get(service_type)
                if service:
                    return service["url_template"].format(instance=instance, feed_name=clean_name)

            # Default to direct Reddit
            service = services["reddit"]
            instance = random.choice(service["instances"])

            # Handle different Reddit URL formats
            if clean_name.startswith('r/'):
                subreddit = clean_name[2:].strip()
                return f"{instance}/r/{subreddit}/.rss"
            elif clean_name.startswith('u/') or clean_name.startswith('user/'):
                username = clean_name[2:] if clean_name.startswith('u/') else clean_name[5:]
                return f"{instance}/user/{username}/.rss"
            else:
                # Assume it's a subreddit
                return f"{instance}/r/{clean_name}/.rss"
        return None

    def validate_feed_name(self, platform, feed_name):
        """Validate feed name format"""
        if platform == "reddit":
            clean_name = re.sub(r'[^a-zA-Z0-9_\-/]', '', feed_name)
            if not clean_name:
                return False, "Invalid Reddit name format"
        return True, feed_name

    async def test_feed_url(self, feed_url, platform, feed_name):
        """Test if a feed URL is accessible with proper error handling"""
        headers = self.get_chromium_headers()

        # Add platform-specific headers
        if platform == "reddit":
            headers['User-Agent'] = 'Mozilla/5.0 (compatible; SocialFeedBot/1.0)'

        async with aiohttp.ClientSession() as session:
            try:
                print(f"🔍 Testing feed URL: {feed_url}")
                async with session.get(feed_url, timeout=15, headers=headers, allow_redirects=True) as response:
                    print(f"📡 Response status: {response.status}")

                    if response.status == 200:
                        text = await response.text()

                        # Check if we got a valid RSS response (including CDATA wrapped content)
                        if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml', '<![CDATA']):
                            # It's a valid RSS feed - parse it
                            feed = feedparser.parse(text)

                            if hasattr(feed, 'bozo') and feed.bozo:
                                print(f"❌ RSS parsing error: {feed.bozo_exception}")
                                return False, f"Invalid RSS feed format"

                            if not feed.entries:
                                print("❌ Feed has no posts")
                                return False, "Feed has no posts"

                            print(f"✅ Success! Found {len(feed.entries)} entries")
                            return True, feed
                        else:
                            # It's not RSS - might be HTML
                            print("❌ Not a valid RSS feed - got HTML instead")
                            return False, "Service returned HTML instead of RSS feed"
                    else:
                        error_msg = f"HTTP {response.status}: {response.reason}"
                        print(f"❌ HTTP error: {error_msg}")
                        return False, error_msg
            except asyncio.TimeoutError:
                print("⏰ Request timeout")
                return False, "Request timeout"
            except aiohttp.ClientError as e:
                print(f"🔌 Connection error: {e}")
                return False, f"Connection error: {str(e)}"
            except Exception as e:
                print(f"💥 Unexpected error: {e}")
                return False, f"Unexpected error: {str(e)}"

    async def finalize(self, interaction: discord.Interaction):
        if not all([self.platform, self.feed_name]):
            embed = discord.Embed(
                title="❌ Error",
                description="Missing platform or feed name!",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        is_valid, fixed_name = self.validate_feed_name(self.platform, self.feed_name)

        if not is_valid:
            embed = discord.Embed(
                title="❌ Invalid Format",
                description=fixed_name,
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if fixed_name != self.feed_name:
            self.feed_name = fixed_name

        # For YouTube, try to resolve username/handle to channel ID and get channel info
        actual_feed_name = self.feed_name
        display_name = self.feed_name
        channel_data = None

        if self.platform == "youtube":
            if self.feed_name.startswith('@') or re.match(r'^UC[\w-]{22}$', self.feed_name):
                resolved_id, resolved_name = await self.resolve_youtube_identifier(self.feed_name)
                if resolved_id:
                    actual_feed_name = resolved_id
                    display_name = resolved_name

                    # Get channel info for embed
                    channel_info = await self.get_youtube_channel_info(resolved_id)
                    if channel_info:
                        channel_data = {
                            'name': channel_info['name'],
                            'thumbnail': channel_info['thumbnail'],
                            'description': channel_info['description']
                        }
                        display_name = channel_info['name']
                else:
                    embed = discord.Embed(
                        title="❌ YouTube Channel Not Found",
                        description=f"Could not find YouTube channel: `{self.feed_name}`\n\n**Tips:**\n• Make sure the channel exists\n• Try using the channel ID instead of handle\n• Channel IDs start with 'UC' and are 24 characters long",
                        color=0xff0000
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

        # Try multiple services and instances
        feed_url = None
        test_feed = None
        working_instance = None
        service_type = None
        successful_services = []

        if self.platform == "twitter":
            services = self.get_twitter_services()
        elif self.platform == "reddit":
            services = self.get_reddit_services()
        else:
            services = {}

        if services:
            # Try all instances of all services
            for service_name, service_info in services.items():
                service_successful = []
                for instance in service_info["instances"]:
                    test_url = service_info["url_template"].format(instance=instance, feed_name=actual_feed_name, username=actual_feed_name.lstrip('@'))
                    success, result = await self.test_feed_url(test_url, self.platform, actual_feed_name)
                    if success:
                        service_successful.append(instance)
                        if not feed_url:  # Use the first successful one
                            feed_url = test_url
                            test_feed = result
                            working_instance = instance
                            service_type = service_name

                if service_successful:
                    successful_services.append({
                        "name": service_info["name"],
                        "emoji": service_info["emoji"],
                        "instances": service_successful,
                        "description": service_info["description"]
                    })

            if not successful_services:
                # All services failed - show attractive error embed
                if self.platform == "twitter":
                    embed = self.create_twitter_error_embed(self.feed_name)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    embed = discord.Embed(
                        title=f"❌ {self.platform.title()} Feed Error",
                        description=f"All {self.platform.title()} services are currently unavailable for `{self.feed_name}`. Please try again later.",
                        color=0xff0000
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                return

            self.successful_services = successful_services
        else:
            # For YouTube and others without multiple services
            feed_url = self.generate_feed_url(self.platform, actual_feed_name)
            if not feed_url:
                embed = discord.Embed(
                    title="❌ Error",
                    description="Could not generate feed URL.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            success, result = await self.test_feed_url(feed_url, self.platform, actual_feed_name)
            if not success:
                embed = discord.Embed(
                    title="❌ Feed Error",
                    description=f"Could not access feed: {result}\n\n**URL:** {feed_url}",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            test_feed = result
            working_instance = "direct"
            service_type = "direct"

        # Extract latest post info
        latest_post_id = None
        latest_post_time = None
        if test_feed.entries:
            latest_post = test_feed.entries[0]
            latest_post_id = latest_post.id if hasattr(latest_post, 'id') else latest_post.link
            if hasattr(latest_post, 'published_parsed') and latest_post.published_parsed:
                latest_post_time = datetime(*latest_post.published_parsed[:6])

        # Save to database
        try:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO SocialFeed(guild_id, channel_id, platform, feed_name, feed_url, last_post_id, last_post_time, last_check_time, working_instance, service_type, mention_text, display_name, channel_data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (interaction.guild.id, interaction.channel.id, self.platform, actual_feed_name, feed_url, latest_post_id, latest_post_time, datetime.now(), working_instance, service_type, self.mention_text, display_name, json.dumps(channel_data) if channel_data else None)
                )
                await db.commit()

            platform_icons = {
                "twitter": TWITTER_ICON,
                "youtube": YOUTUBE_ICON,
                "reddit": REDDIT_ICON
            }

            # Create beautiful success embed
            embed = discord.Embed(
                title="🎉 Feed Added Successfully!",
                color=NEPAL_BLUE,
                timestamp=datetime.utcnow()
            )

            embed.set_thumbnail(url=platform_icons.get(self.platform, DISCORD_ICON))

            embed.add_field(
                name="📱 Platform",
                value=f"**{self.platform.title()}**",
                inline=True
            )

            embed.add_field(
                name="👤 Display Name",
                value=f"`{display_name}`",
                inline=True
            )

            if self.platform == "youtube" and display_name != actual_feed_name:
                embed.add_field(
                    name="🆔 Channel ID",
                    value=f"`{actual_feed_name}`",
                    inline=True
                )

            embed.add_field(
                name="📋 Channel",
                value=interaction.channel.mention,
                inline=True
            )

            if self.mention_text:
                embed.add_field(
                    name="🔔 Mentions",
                    value=self.mention_text,
                    inline=True
                )

            if successful_services:
                service_info = ""
                for service in successful_services:
                    service_info += f"{service['emoji']} **{service['name']}**: {len(service['instances'])} instances\n"

                embed.add_field(
                    name="🌐 Available Services",
                    value=service_info,
                    inline=False
                )

                embed.add_field(
                    name="⚡ Primary Service",
                    value=f"**{service_type.title()}** • `{working_instance}`",
                    inline=True
                )

            embed.set_footer(text="🚀 Social Feed System • Updates every 60 seconds", icon_url=DISCORD_ICON)
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Database Error",
                description=f"An error occurred while saving the feed: {str(e)}",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

class SocialFeed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = None
        self.session = None
        self.is_checking = False

    async def cog_load(self) -> None:
        await init_db()
        self.db = await aiosqlite.connect(db_path)
        self.session = aiohttp.ClientSession()
        self.check_feeds.start()

    async def cog_unload(self) -> None:
        self.check_feeds.cancel()
        if self.db:
            await self.db.close()
        if self.session:
            await self.session.close()

    def get_chromium_headers(self):
        """Get realistic Chromium browser headers to avoid detection"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        ]

        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

    def clean_html_content(self, html_content):
        """Clean HTML content from RSS feed descriptions"""
        if not html_content:
            return ""

        # Remove CDATA wrapper if present
        if html_content.startswith('<![CDATA[') and html_content.endswith(']]>'):
            html_content = html_content[9:-3]

        # Remove HTML tags but keep text content
        clean_text = re.sub('<[^<]+?>', '', html_content)

        # Clean up extra whitespace
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        return clean_text

    def extract_image_urls_from_description(self, description):
        """Extract image URLs from RSS feed description"""
        if not description:
            return []

        # Look for img tags in the description
        img_pattern = r'<img[^>]+src="([^"]+)"'
        image_urls = re.findall(img_pattern, description)

        return image_urls

    def extract_media_urls(self, platform, entry):
        """Extract image and video URLs from feed entry"""
        media_urls = []
        direct_video_urls = []

        if platform == "reddit":
            # Reddit media extraction
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                for thumb in entry.media_thumbnail:
                    if hasattr(thumb, 'url') and thumb.url:
                        media_urls.append(thumb.url)

            if hasattr(entry, 'media_content') and entry.media_content:
                for media in entry.media_content:
                    if hasattr(media, 'url') and media.url:
                        media_urls.append(media.url)
                        if any(ext in media.url.lower() for ext in ['.mp4', '.mov', '.avi', '.webm']):
                            direct_video_urls.append(media.url)

        elif platform == "twitter":
            # Twitter media extraction - check both standard attributes and description
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                for thumb in entry.media_thumbnail:
                    if hasattr(thumb, 'url') and thumb.url:
                        media_urls.append(thumb.url)

            # Extract images from description (for Nitter RSS feeds with CDATA)
            if hasattr(entry, 'description') and entry.description:
                image_urls = self.extract_image_urls_from_description(entry.description)
                media_urls.extend(image_urls)

        elif platform == "youtube":
            # Extract YouTube video ID for embedding
            video_id = None
            if hasattr(entry, 'yt_videoid'):
                video_id = entry.yt_videoid
            elif hasattr(entry, 'link'):
                yt_match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([^&?\s]+)', entry.link)
                if yt_match:
                    video_id = yt_match.group(1)

            if video_id:
                thumbnails = [
                    f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                    f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
                ]
                media_urls.extend(thumbnails)

        return media_urls, direct_video_urls

    def create_post_embed(self, platform, feed_name, post_data, channel_data=None, is_test=False):
        """Create a beautiful embed for social media posts"""
        platform_configs = {
            "twitter": {
                "color": TWITTER_BLUE,
                "author_format": "{}",
                "thumbnail": TWITTER_ICON,
            },
            "youtube": {
                "color": YOUTUBE_RED,
                "author_format": "{}",
                "thumbnail": YOUTUBE_ICON,
            },
            "reddit": {
                "color": REDDIT_ORANGE,
                "author_format": "{}",
                "thumbnail": REDDIT_ICON,
            }
        }

        config = platform_configs.get(platform, platform_configs["twitter"])

        # Use channel thumbnail for YouTube if available
        author_thumbnail = config["thumbnail"]
        if platform == "youtube" and channel_data and channel_data.get('thumbnail'):
            author_thumbnail = channel_data['thumbnail']

        # Create main embed
        embed = discord.Embed(color=config["color"], timestamp=datetime.utcnow())

        # Set embed thumbnail to platform icon
        embed.set_thumbnail(url=author_thumbnail)

        # Title
        title = post_data.get('title', 'New Post')
        if len(title) > 200:
            title = title[:197] + "..."

        if is_test:
            embed.title = f"🧪 TEST POST • {title}"
        else:
            embed.title = title

        embed.url = post_data.get('link', '')

        # Description with clean formatting
        description = post_data.get('summary', post_data.get('description', ''))
        if description:
            # Clean HTML tags and extra whitespace from CDATA content
            description = self.clean_html_content(description)
            if len(description) > 500:
                description = description[:497] + "..."
            embed.description = description

        # Author with platform info
        author_name = config['author_format'].format(feed_name)
        embed.set_author(name=author_name, icon_url=author_thumbnail, url=post_data.get('link', ''))

        media_urls = post_data.get('media_urls', [])
        image_urls = [url for url in media_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])]

        # Handle YouTube videos - set thumbnail as main image
        if platform == "youtube":
            youtube_thumbs = [url for url in image_urls if 'youtube.com/vi' in url or 'ytimg.com' in url]
            if youtube_thumbs:
                for quality in ['maxresdefault.jpg', 'sddefault.jpg']:
                    for thumb in youtube_thumbs:
                        if quality in thumb:
                            embed.set_image(url=thumb)
                            break
                    if embed.image and embed.image.url:
                        break

        # Handle images for other platforms
        elif image_urls:
            embed.set_image(url=image_urls[0])

        # Add post date if available
        if post_data.get('published'):
            try:
                published = post_data['published']
                if hasattr(published, 'strftime'):
                    embed.add_field(
                        name="🕒 Posted",
                        value=f"<t:{int(published.timestamp())}:R>",
                        inline=True
                    )
            except:
                pass

        # Footer with platform info
        platform_icons = {
            "twitter": TWITTER_ICON,
            "youtube": YOUTUBE_ICON,
            "reddit": REDDIT_ICON
        }

        if is_test:
            embed.set_footer(text=f"🧪 Test Feed • {platform.title()}", icon_url=platform_icons.get(platform, DISCORD_ICON))
        else:
            embed.set_footer(text=f"🌟 Social Feed • {platform.title()} • Powered by NPL Utils", icon_url=platform_icons.get(platform, DISCORD_ICON))

        return embed

    def get_twitter_services(self):
        """Get list of WORKING Twitter service alternatives with all instances"""
        return {
            "nitter": {
                "instances": [
                    "https://xcancel.com",
                    "https://nitter.privacyredirect.com",
                    "https://nitter.poast.org",
                    "https://nuku.trabun.org",
                    "https://nitter.space",
                    "https://lightbrd.com",
                    "https://nitter.net",
                    "https://nitter.tiekoetter.com",
                    "https://nitter.weiler.rocks",
                    "https://nitter.privacydev.net"
                ],
                "url_template": "{instance}/{username}/rss",
                "name": "Nitter",
                "emoji": "🔵",
                "description": "Privacy-focused Twitter frontend"
            },
            "rsshub": {
                "instances": [
                    "https://rsshub.app",
                    "https://rsshub.rssforever.com",
                ],
                "url_template": "{instance}/twitter/user/{username}",
                "name": "RSSHub",
                "emoji": "🔗",
                "description": "Universal RSS generator"
            }
        }

    def get_reddit_services(self):
        """Get list of Reddit service alternatives"""
        return {
            "reddit": {
                "instances": [
                    "https://www.reddit.com",
                    "https://old.reddit.com"
                ],
                "url_template": "{instance}/{feed_name}/.rss",
                "name": "Reddit",
                "emoji": "🟠",
                "description": "Direct Reddit RSS"
            },
            "rsshub": {
                "instances": [
                    "https://rsshub.app",
                    "https://rsshub.rssforever.com"
                ],
                "url_template": "{instance}/reddit/{feed_name}",
                "name": "RSSHub",
                "emoji": "🔗",
                "description": "Universal RSS generator"
            }
        }

    async def fetch_feed_with_fallback(self, feed_url, platform, feed_name, current_instance=None, service_type=None):
        """Fetch feed with fallback to other services and instances"""
        headers = self.get_chromium_headers()

        if platform == "reddit":
            headers['User-Agent'] = 'Mozilla/5.0 (compatible; SocialFeedBot/1.0)'

        # Try current instance first
        try:
            async with self.session.get(feed_url, timeout=15, headers=headers, allow_redirects=True) as response:
                if response.status == 200:
                    text = await response.text()
                    # Check for valid RSS (including CDATA content)
                    if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml', '<![CDATA']):
                        feed = feedparser.parse(text)
                        if not hasattr(feed, 'bozo') or not feed.bozo:
                            if feed.entries:
                                return feed, current_instance, service_type
        except Exception:
            pass

        # If current instance fails, try other services and instances
        if platform == "twitter":
            services = self.get_twitter_services()
        elif platform == "reddit":
            services = self.get_reddit_services()
        else:
            return None, current_instance, service_type

        # Try all instances of all services
        for new_service_type, service_info in services.items():
            if new_service_type == service_type:
                continue

            for instance in service_info["instances"]:
                try:
                    if platform == "twitter":
                        new_feed_url = service_info["url_template"].format(instance=instance, username=feed_name.lstrip('@'))
                    else:
                        new_feed_url = service_info["url_template"].format(instance=instance, feed_name=feed_name)

                    async with self.session.get(new_feed_url, timeout=10, headers=headers, allow_redirects=True) as response:
                        if response.status == 200:
                            text = await response.text()
                            if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml', '<![CDATA']):
                                feed = feedparser.parse(text)
                                if not hasattr(feed, 'bozo') or not feed.bozo:
                                    if feed.entries:
                                        return feed, instance, new_service_type
                except Exception:
                    continue

        return None, current_instance, service_type

    @tasks.loop(seconds=60)
    async def check_feeds(self):
        """Check all feeds for new posts with service fallback"""
        if self.is_checking:
            return

        self.is_checking = True
        try:
            async with self.db.execute("SELECT guild_id, channel_id, platform, feed_name, feed_url, last_post_id, working_instance, service_type, mention_text, display_name, channel_data FROM SocialFeed") as cursor:
                feeds = await cursor.fetchall()

            for guild_id, channel_id, platform, feed_name, feed_url, last_post_id, working_instance, service_type, mention_text, display_name, channel_data_json in feeds:
                try:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        continue

                    # Parse channel data
                    channel_data = None
                    if channel_data_json:
                        try:
                            channel_data = json.loads(channel_data_json)
                        except:
                            pass

                    # Use display name if available
                    actual_feed_name = display_name if display_name else feed_name

                    # Use fallback system for Twitter and Reddit feeds
                    if platform in ["twitter", "reddit"]:
                        feed, new_instance, new_service_type = await self.fetch_feed_with_fallback(
                            feed_url, platform, feed_name, working_instance, service_type
                        )
                    else:
                        # For YouTube and other platforms
                        headers = self.get_chromium_headers()
                        try:
                            async with self.session.get(feed_url, timeout=15, headers=headers, allow_redirects=True) as response:
                                if response.status == 200:
                                    text = await response.text()
                                    if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml', '<![CDATA']):
                                        feed = feedparser.parse(text)
                                    else:
                                        feed = None
                                else:
                                    feed = None
                        except:
                            feed = None

                    if not feed or not feed.entries:
                        continue

                    latest_post = feed.entries[0]
                    current_post_id = latest_post.id if hasattr(latest_post, 'id') else latest_post.link

                    if current_post_id != last_post_id:
                        # Extract media URLs
                        media_urls, direct_video_urls = self.extract_media_urls(platform, latest_post)

                        # Clean description if it contains CDATA/HTML
                        description = getattr(latest_post, 'summary', getattr(latest_post, 'description', ''))
                        clean_description = self.clean_html_content(description)

                        post_data = {
                            'title': latest_post.title,
                            'link': latest_post.link,
                            'summary': clean_description,
                            'description': clean_description,
                            'published': getattr(latest_post, 'published_parsed', None),
                            'media_urls': media_urls,
                            'direct_video_urls': direct_video_urls
                        }

                        # Create embed
                        embed = self.create_post_embed(platform, actual_feed_name, post_data, channel_data)

                        try:
                            # Send mention if configured
                            if mention_text:
                                await channel.send(f"🔔 {mention_text}")

                            # Get first direct video URL for play button
                            direct_video_url = direct_video_urls[0] if direct_video_urls else None

                            # Create view with watch button
                            view = WatchButton(post_data['link'], platform, direct_video_url)

                            # Send embed with button
                            await channel.send(embed=embed, view=view)

                            post_time = None
                            if hasattr(latest_post, 'published_parsed') and latest_post.published_parsed:
                                post_time = datetime(*latest_post.published_parsed[:6])

                            # Update database
                            async with self.db.execute(
                                "UPDATE SocialFeed SET last_post_id = ?, last_post_time = ?, last_check_time = ?, working_instance = ?, service_type = ? WHERE guild_id = ? AND feed_name = ?",
                                (current_post_id, post_time, datetime.now(), working_instance, service_type, guild_id, feed_name)
                            ):
                                await self.db.commit()

                        except discord.Forbidden:
                            print(f"No permission to send messages in {channel.name}")
                        except Exception as e:
                            print(f"Error sending message to {channel.name}: {e}")
                    else:
                        # Update last check time
                        async with self.db.execute(
                            "UPDATE SocialFeed SET last_check_time = ? WHERE guild_id = ? AND feed_name = ?",
                            (datetime.now(), guild_id, feed_name)
                        ):
                            await self.db.commit()

                except Exception as e:
                    print(f"Error processing feed {feed_name} for guild {guild_id}: {e}")
                    continue

        except Exception as e:
            print(f"Error in check_feeds: {e}")
        finally:
            self.is_checking = False

    # ----------------- Commands -----------------
    @commands.hybrid_command(name="socialfeed", description="Add a social media feed")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def socialfeed(self, ctx):
        """Main social feed command - opens dialog box"""
        view = SocialFeedView(self.bot)
        embed = discord.Embed(
            title="📰 Add Social Media Feed",
            description="✨ **Select a platform from the dropdown below to get started!**\n\n"
                       "• 🐦 **Twitter/X** - Follow Twitter/X accounts\n"
                       "• 📺 **YouTube** - Subscribe to YouTube channels\n"
                       "• 🤖 **Reddit** - Follow subreddits and users",
            color=NEPAL_BLUE
        )
        embed.set_footer(text="🎯 Powered by NPL Utils • Manage your social feeds efficiently")
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @commands.hybrid_command(name="socialfeed_lastpost", description="Get the last posted content from a feed")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def last_post(self, ctx, feed_name: str):
        """Get the last posted content from a feed"""
        await ctx.defer(ephemeral=True)

        async with self.db.execute(
            "SELECT platform, feed_name, feed_url, last_post_id, last_post_time, working_instance, service_type, mention_text, display_name, channel_data FROM SocialFeed WHERE guild_id = ? AND feed_name = ?",
            (ctx.guild.id, feed_name)
        ) as cursor:
            feed = await cursor.fetchone()

        if not feed:
            embed = discord.Embed(
                title="❌ Feed Not Found",
                description=f"No feed found with name `{feed_name}`",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        platform, feed_name, feed_url, last_post_id, last_post_time, working_instance, service_type, mention_text, display_name, channel_data_json = feed

        # Parse channel data
        channel_data = None
        if channel_data_json:
            try:
                channel_data = json.loads(channel_data_json)
            except:
                pass

        # Use display name if available
        actual_feed_name = display_name if display_name else feed_name

        # Use fallback system for fetching
        if platform in ["twitter", "reddit"]:
            feed_data, _, _ = await self.fetch_feed_with_fallback(feed_url, platform, feed_name, working_instance, service_type)
        else:
            headers = self.get_chromium_headers()
            async with self.session.get(feed_url, timeout=15, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    feed_data = feedparser.parse(text) if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml', '<![CDATA']) else None
                else:
                    feed_data = None

        if not feed_data or not feed_data.entries:
            embed = discord.Embed(
                title="❌ No Posts Found",
                description="Could not fetch feed or no posts found.",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        last_post = None
        for entry in feed_data.entries:
            entry_id = entry.id if hasattr(entry, 'id') else entry.link
            if entry_id == last_post_id:
                last_post = entry
                break

        if not last_post:
            last_post = feed_data.entries[0]

        # Extract media URLs including direct video URLs
        media_urls, direct_video_urls = self.extract_media_urls(platform, last_post)

        # Clean description
        description = getattr(last_post, 'summary', getattr(last_post, 'description', ''))
        clean_description = self.clean_html_content(description)

        post_data = {
            'title': last_post.title,
            'link': last_post.link,
            'summary': clean_description,
            'description': clean_description,
            'published': getattr(last_post, 'published_parsed', None),
            'media_thumbnail': getattr(last_post, 'media_thumbnail', None),
            'media_content': getattr(last_post, 'media_content', None),
            'media_urls': media_urls,
            'direct_video_urls': direct_video_urls
        }

        embed = self.create_post_embed(platform, actual_feed_name, post_data, channel_data, is_test=True)

        # Add service information
        if platform in ["twitter", "reddit"] and service_type:
            if platform == "twitter":
                services = self.get_twitter_services()
            else:
                services = self.get_reddit_services()

            service_info = services.get(service_type, {})
            embed.add_field(
                name="🌐 Service",
                value=f"{service_info.get('emoji', '🔗')} **{service_info.get('name', 'Unknown')}**\n`{working_instance}`",
                inline=True
            )

        # Add mention information
        if mention_text:
            embed.add_field(
                name="🔔 Mentions",
                value=mention_text,
                inline=True
            )

        if last_post_time:
            if isinstance(last_post_time, str):
                try:
                    last_post_time = datetime.fromisoformat(last_post_time.replace('Z', '+00:00'))
                except:
                    last_post_time = None

            if last_post_time and hasattr(last_post_time, 'timestamp'):
                embed.add_field(
                    name="📅 Last Posted",
                    value=f"<t:{int(last_post_time.timestamp())}:R>",
                    inline=True
                )
        elif hasattr(last_post, 'published_parsed') and last_post.published_parsed:
            post_time = datetime(*last_post.published_parsed[:6])
            embed.add_field(
                name="📅 Post Created",
                value=f"<t:{int(post_time.timestamp())}:R>",
                inline=True
            )

        embed.add_field(
            name="🆔 Post ID",
            value=f"`{last_post_id[:20]}...`" if last_post_id and len(last_post_id) > 20 else f"`{last_post_id}`",
            inline=True
        )

        # Get first direct video URL for play button
        direct_video_url = direct_video_urls[0] if direct_video_urls else None

        # Create view with watch button and play button if available
        view = WatchButton(post_data['link'], platform, direct_video_url)
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @commands.hybrid_command(name="socialfeed_latest", description="Get the latest post from a feed")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def latest_feed(self, ctx, feed_name: str):
        """Get the latest post from a feed to test it"""
        await ctx.defer(ephemeral=True)

        async with self.db.execute(
            "SELECT platform, feed_name, feed_url, last_post_id, last_check_time, working_instance, service_type, mention_text, display_name, channel_data FROM SocialFeed WHERE guild_id = ? AND feed_name = ?",
            (ctx.guild.id, feed_name)
        ) as cursor:
            feed = await cursor.fetchone()

        if not feed:
            embed = discord.Embed(
                title="❌ Feed Not Found",
                description=f"No feed found with name `{feed_name}`",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        platform, feed_name, feed_url, last_post_id, last_check_time, working_instance, service_type, mention_text, display_name, channel_data_json = feed

        # Parse channel data
        channel_data = None
        if channel_data_json:
            try:
                channel_data = json.loads(channel_data_json)
            except:
                pass

        # Use display name if available
        actual_feed_name = display_name if display_name else feed_name

        # Use fallback system for fetching
        if platform in ["twitter", "reddit"]:
            feed_data, new_instance, new_service_type = await self.fetch_feed_with_fallback(feed_url, platform, feed_name, working_instance, service_type)
        else:
            headers = self.get_chromium_headers()
            async with self.session.get(feed_url, timeout=15, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    feed_data = feedparser.parse(text) if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml', '<![CDATA']) else None
                else:
                    feed_data = None

        if not feed_data or not feed_data.entries:
            embed = discord.Embed(
                title="❌ Test Failed",
                description="Could not fetch feed or no posts found.",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        latest_post = feed_data.entries[0]

        # Extract media URLs including direct video URLs
        media_urls, direct_video_urls = self.extract_media_urls(platform, latest_post)

        # Clean description
        description = getattr(latest_post, 'summary', getattr(latest_post, 'description', ''))
        clean_description = self.clean_html_content(description)

        post_data = {
            'title': latest_post.title,
            'link': latest_post.link,
            'summary': clean_description,
            'description': clean_description,
            'published': getattr(latest_post, 'published_parsed', None),
            'media_thumbnail': getattr(latest_post, 'media_thumbnail', None),
            'media_content': getattr(latest_post, 'media_content', None),
            'media_urls': media_urls,
            'direct_video_urls': direct_video_urls
        }

        embed = self.create_post_embed(platform, actual_feed_name, post_data, channel_data, is_test=True)

        # Add service information
        if platform in ["twitter", "reddit"]:
            current_service_type = new_service_type if new_service_type else service_type
            current_instance = new_instance if new_instance else working_instance

            if platform == "twitter":
                services = self.get_twitter_services()
            else:
                services = self.get_reddit_services()

            service_info = services.get(current_service_type, {})
            embed.add_field(
                name="🌐 Service",
                value=f"{service_info.get('emoji', '🔗')} **{service_info.get('name', 'Unknown')}**\n`{current_instance}`",
                inline=True
            )

        # Add mention information
        if mention_text:
            embed.add_field(
                name="🔔 Mentions",
                value=mention_text,
                inline=True
            )

        if last_check_time:
            if isinstance(last_check_time, str):
                try:
                    last_check_time = datetime.fromisoformat(last_check_time.replace('Z', '+00:00'))
                except:
                    last_check_time = None

            if last_check_time and hasattr(last_check_time, 'timestamp'):
                embed.add_field(
                    name="⏰ Last Checked",
                    value=f"<t:{int(last_check_time.timestamp())}:R>",
                    inline=True
                )

        embed.add_field(
            name="🆔 Current Post ID",
            value=f"`{last_post_id[:20]}...`" if last_post_id and len(last_post_id) > 20 else f"`{last_post_id}`",
            inline=True
        )

        # Get first direct video URL for play button
        direct_video_url = direct_video_urls[0] if direct_video_urls else None

        # Create view with watch button and play button if available
        view = WatchButton(post_data['link'], platform, direct_video_url)
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @commands.hybrid_command(name="socialfeed_remove", description="Remove a social media feed")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def remove_feed(self, ctx, feed_name: str):
        """Remove a social media feed"""
        await ctx.defer(ephemeral=True)

        async with self.db.execute(
            "DELETE FROM SocialFeed WHERE guild_id = ? AND feed_name = ?",
            (ctx.guild.id, feed_name)
        ) as cursor:
            await self.db.commit()

            if cursor.rowcount > 0:
                embed = discord.Embed(
                    title="🗑️ Feed Removed Successfully",
                    description=f"**{feed_name}** has been removed from your social feeds.",
                    color=NEPAL_BLUE
                )
                embed.set_footer(text="✅ Feed management • NPL Utils")
            else:
                embed = discord.Embed(
                    title="❌ Feed Not Found",
                    description=f"No feed found with name `{feed_name}`",
                    color=0xff0000
                )

            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="socialfeed_list", description="List all social media feeds")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @app_commands.guild_only()
    async def list_feeds(self, ctx):
        """List all configured social media feeds"""
        await ctx.defer(ephemeral=True)

        try:
            async with self.db.execute(
                "SELECT platform, feed_name, channel_id, last_post_time, last_check_time, working_instance, service_type, mention_text, display_name FROM SocialFeed WHERE guild_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                embed = discord.Embed(
                    title="📰 No Social Feeds",
                    description="You haven't added any social feeds yet!\n\n"
                               "Use `/socialfeed` to add your first feed and start receiving updates.",
                    color=NEPAL_BLUE
                )
                embed.set_footer(text="🚀 Get started with NPL Utils Social Feeds")
                await ctx.send(embed=embed, ephemeral=True)
                return

            embed = discord.Embed(
                title=f"📰 Your Social Feeds",
                color=NEPAL_BLUE,
                timestamp=datetime.utcnow()
            )

            for platform, feed_name, channel_id, last_post_time, last_check_time, working_instance, service_type, mention_text, display_name in rows:
                platform_emojis = {"twitter": "🐦", "youtube": "📺", "reddit": "🤖"}
                emoji = platform_emojis.get(platform, "📰")

                # Use display name if available
                actual_display_name = display_name if display_name else feed_name

                embed.add_field(
                    name=f"{emoji} {actual_display_name}",
                    value=f"**Platform:** {platform.title()}\n**Channel:** <#{channel_id}>",
                    inline=True
                )

            embed.set_footer(text=f"📊 Total feeds: {len(rows)} • 🔄 Updates every 60 seconds")
            await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while fetching feeds: {str(e)}",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)

    @check_feeds.before_loop
    async def before_check_feeds(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(SocialFeed(bot))
