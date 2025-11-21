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
import html
import time
import logging
from typing import Optional, List, Dict, Any
from utils.Tools import *
import requests
from urllib.parse import quote

# Twitter configuration - USE EXACT SAME AS STANDALONE
TWITTER_CONFIG = {
    "NITTER_INSTANCES": [
        "https://nitter.privacyredirect.com",
        "https://nitter.net",
        "https://nitter.it",
        "https://nitter.unixfox.eu"
    ],
    "CHECK_INTERVAL": 180,  # Changed to 3 minutes
    "MAX_RETRIES": 3,
    "RETRY_DELAY": 60,
    "USE_FXEMBED": True,
    "FXEMBED_MODE": "enhanced"
}

# Global Twitter variables
twitter_current_instance_index = 0
twitter_retry_count = 0

db_folder = 'db'
db_file = 'social_feed.db'
db_path = os.path.join(db_folder, db_file)

# Colors
NEPAL_BLUE = 0x003893
TWITTER_BLUE = 0x1DA1F2
YOUTUBE_RED = 0xFF0000
REDDIT_ORANGE = 0xFF5700

# Social media icons
TWITTER_ICON = "https://abs.twimg.com/favicons/twitter.2.ico"
YOUTUBE_ICON = "https://www.youtube.com/s/desktop/5c6daf13/img/favicon_144x144.png"
REDDIT_ICON = "https://www.redditstatic.com/icon.png"
DISCORD_ICON = "https://assets-global.website-files.com/6257adef93867e50d84d30e2/636e0a6a49cf127bf92de1e2_icon_clyde_blurple_RGB.png"

async def init_db():
    if not os.path.exists(db_folder):
        os.makedirs(db_folder)
    async with aiosqlite.connect(db_path) as db:
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

# --------------------------
# EXACT SAME FxEmbed from standalone script
# --------------------------
class FxEmbed:
    """FxEmbed integration for enhanced Twitter links"""

    @staticmethod
    def convert_twitter_url(original_url: str, mode: str = "enhanced", translate: Optional[str] = None) -> str:
        """
        Convert Twitter/X URL to FxEmbed enhanced URL.

        Modes:
        - enhanced: Regular enhanced embed (default)
        - gallery: Gallery view (g.fxtwitter.com)
        - text: Text-only view (t.fxtwitter.com)
        - direct: Direct media links (d.fxtwitter.com)
        - mosaic: Combined mosaic image (m.fxtwitter.com)
        """
        # Extract tweet ID from various URL formats
        tweet_id = FxEmbed.extract_tweet_id(original_url)
        if not tweet_id:
            return original_url

        # Determine base domain and subdomain
        if "x.com" in original_url:
            base_domain = "fixupx.com"
            original_domain = "x.com"
        else:
            base_domain = "fxtwitter.com"
            original_domain = "twitter.com"

        # Apply mode-specific subdomain
        if mode == "gallery":
            subdomain = "g."
        elif mode == "text":
            subdomain = "t."
        elif mode == "direct":
            subdomain = "d."
        elif mode == "mosaic":
            subdomain = "m."
        else:  # enhanced
            subdomain = ""

        # Reconstruct URL with FxEmbed
        username = FxEmbed.extract_username(original_url)
        if not username:
            username = "i"  # fallback for intent URLs

        new_url = f"https://{subdomain}{base_domain}/{username}/status/{tweet_id}"

        # Add translation if requested
        if translate:
            new_url += f"/{translate}"

        return new_url

    @staticmethod
    def extract_tweet_id(url: str) -> Optional[str]:
        """Extract tweet ID from various Twitter URL formats."""
        patterns = [
            r'status/(\d+)',
            r'twitter\.com/\w+/status/(\d+)',
            r'x\.com/\w+/status/(\d+)',
            r'nitter\.\w+/\w+/status/(\d+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def extract_username(url: str) -> Optional[str]:
        """Extract username from Twitter URL."""
        patterns = [
            r'twitter\.com/([^/]+)/status',
            r'x\.com/([^/]+)/status',
            r'nitter\.\w+/([^/]+)/status'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

# --------------------------
# EXACT SAME Twitter Monitor from standalone script (SYNCHRONOUS)
# --------------------------
class TwitterMonitor:
    """EXACT SAME Twitter monitoring logic from standalone script"""

    @staticmethod
    def get_current_rss_url(feed_name: str) -> str:
        """Get RSS URL from current Nitter instance."""
        global twitter_current_instance_index
        base_url = TWITTER_CONFIG["NITTER_INSTANCES"][twitter_current_instance_index]
        return f"{base_url}/{feed_name.lstrip('@')}/rss"

    @staticmethod
    def rotate_nitter_instance() -> None:
        """Switch to next Nitter instance if current one fails."""
        global twitter_current_instance_index
        twitter_current_instance_index = (twitter_current_instance_index + 1) % len(TWITTER_CONFIG["NITTER_INSTANCES"])
        print(f"🔄 Switched to Nitter instance: {TWITTER_CONFIG['NITTER_INSTANCES'][twitter_current_instance_index]}")

    @staticmethod
    def clean_html(text: str) -> str:
        """Remove HTML tags and clean up text."""
        if not text:
            return ""

        text = html.unescape(text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @staticmethod
    def extract_tweet_content(description: str) -> Dict[str, Any]:
        """Extract clean text and images from tweet description."""
        if not description:
            return {"text": "", "images": []}

        # Extract images
        image_pattern = r'<img src="([^"]+)"'
        images = re.findall(image_pattern, description)

        # Clean text
        clean_text = TwitterMonitor.clean_html(description)
        clean_text = re.sub(r'pic\.twitter\.com/\w+', '', clean_text)
        clean_text = re.sub(r'https?://\S+', '', clean_text)

        return {
            "text": clean_text,
            "images": images
        }

    @staticmethod
    def fetch_latest_tweet(feed_name: str) -> Optional[feedparser.FeedParserDict]:
        """Fetch the most recent tweet from RSS feed - EXACT SAME AS STANDALONE"""
        global twitter_retry_count

        try:
            rss_url = TwitterMonitor.get_current_rss_url(feed_name)
            print(f"🔍 Fetching Twitter feed: {rss_url}")

            # EXACT SAME AS STANDALONE: Use feedparser directly (synchronous)
            feed = feedparser.parse(rss_url)

            # EXACT SAME AS STANDALONE: Handle bozo errors but continue
            if hasattr(feed, 'bozo') and feed.bozo:
                print(f"⚠️ Feed parsing warning: {feed.bozo_exception}")
                TwitterMonitor.rotate_nitter_instance()
                return None

            if not feed.entries:
                print("❌ No tweets found in the feed.")
                twitter_retry_count = 0
                return None

            twitter_retry_count = 0
            print(f"✅ Found {len(feed.entries)} tweets")
            return feed.entries[0]

        except Exception as e:
            print(f"❌ Error fetching tweets: {e}")
            twitter_retry_count += 1

            if twitter_retry_count >= TWITTER_CONFIG["MAX_RETRIES"]:
                print(f"🔄 Max retries exceeded. Rotating Nitter instance.")
                TwitterMonitor.rotate_nitter_instance()
                twitter_retry_count = 0
                time.sleep(TWITTER_CONFIG["RETRY_DELAY"])

            return None

    @staticmethod
    def create_twitter_message(tweet: feedparser.FeedParserDict, feed_name: str) -> str:
        """Create Twitter message with enhanced link (EXACT same as standalone)."""
        content = TwitterMonitor.extract_tweet_content(tweet.description)
        enhanced_url = FxEmbed.convert_twitter_url(
            tweet.link,
            TWITTER_CONFIG["FXEMBED_MODE"]
        )

        username = feed_name.lstrip('@')
        message = f"New Post From **[@{username}]({enhanced_url})**"
        return message

# --------------------------
# YouTube Channel Scraper (ONLY FOR FINDING CHANNEL ID)
# --------------------------
class YouTubeChannelScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        })

    def get_channel_id_from_name(self, name):
        """Get channel ID from channel name with improved error handling"""
        try:
            search_url = f"https://www.youtube.com/results?search_query={quote(name)}&sp=EgIQAg%253D%253D"
            response = self.session.get(search_url)
            response.raise_for_status()

            # Extract ytInitialData JSON from HTML
            match = re.search(r"var ytInitialData = ({.*?});</script>", response.text)
            if not match:
                print("Could not find ytInitialData in response")
                return None

            data = json.loads(match.group(1))

            # Navigate through the complex JSON structure to find channel results
            contents = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])

            for section in contents:
                items = section.get("itemSectionRenderer", {}).get("contents", [])
                for item in items:
                    # Check for channel renderer
                    channel = item.get("channelRenderer")
                    if channel:
                        channel_id = channel.get("channelId")
                        if channel_id:
                            return channel_id

                    # Alternative method: look for channel links in other renderers
                    for key in item:
                        if 'Renderer' in key and 'channelId' in item[key]:
                            channel_id = item[key].get('channelId')
                            if channel_id:
                                return channel_id

            return None

        except requests.RequestException as e:
            print(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None

    def get_channel_info(self, channel_name):
        """Convenience method to get channel ID"""
        print(f"Searching for channel: {channel_name}")
        channel_id = self.get_channel_id_from_name(channel_name)

        if not channel_id:
            print("Channel not found or error occurred")
            return None

        print(f"Found channel ID: {channel_id}")
        return channel_id

# --------------------------
# RxEmbed for Reddit (Fixed - Simple Domain Replacement)
# --------------------------
class RxEmbed:
    """RxEmbed integration for enhanced Reddit links"""

    @staticmethod
    def convert_reddit_url(original_url: str) -> str:
        """
        Convert Reddit URL to RxEmbed enhanced URL.
        Simply replace reddit.com with rxddit.com
        """
        # Simple domain replacement
        if 'reddit.com' in original_url:
            return original_url.replace('reddit.com', 'rxddit.com')
        elif 'redd.it' in original_url:
            return original_url.replace('redd.it', 'rxddit.com')

        return original_url

class SocialFeedView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot
        self.platform = None
        self.feed_name = None
        self.mention_text = None
        self.youtube_scraper = YouTubeChannelScraper()
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

    def generate_feed_url(self, platform, feed_name):
        """Generate appropriate RSS feed URL based on platform"""
        if platform == "twitter":
            clean_name = feed_name.lstrip('@')
            instance = TWITTER_CONFIG["NITTER_INSTANCES"][twitter_current_instance_index]
            return f"{instance}/{clean_name}/rss"

        elif platform == "youtube":
            # For YouTube, use the channel ID directly with YouTube RSS
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={feed_name}"

        elif platform == "reddit":
            clean_name = feed_name.lower().strip()

            # Handle different Reddit URL formats
            if clean_name.startswith('r/'):
                subreddit = clean_name[2:].strip()
                return f"https://www.reddit.com/r/{subreddit}/new/.rss"
            elif clean_name.startswith('u/') or clean_name.startswith('user/'):
                username = clean_name[2:] if clean_name.startswith('u/') else clean_name[5:]
                return f"https://www.reddit.com/user/{username}/submitted/.rss"
            else:
                # Assume it's a subreddit
                return f"https://www.reddit.com/r/{clean_name}/new/.rss"

        return None

    def validate_feed_name(self, platform, feed_name):
        """Validate feed name format"""
        if platform == "reddit":
            clean_name = re.sub(r'[^a-zA-Z0-9_\-/]', '', feed_name)
            if not clean_name:
                return False, "Invalid Reddit name format"
        return True, feed_name
    async def test_twitter_feed(self, feed_name: str):
        """Test Twitter feed using EXACT SAME synchronous approach as standalone"""
        print(f"🔍 Testing Twitter feed for: {feed_name}")

        # Use EXACT SAME synchronous approach as standalone
        tweet = await asyncio.get_event_loop().run_in_executor(
            None, TwitterMonitor.fetch_latest_tweet, feed_name
        )

        if tweet is None:
            return False, "Could not fetch tweets from any Nitter instance"

        # Create a mock feed object with entries to match the expected format
        mock_feed = type('MockFeed', (), {
            'entries': [tweet],
            'bozo': 0
        })()

        return True, mock_feed  # ← Return feed object, not single tweet

    async def test_feed_url(self, feed_url, platform, feed_name):
        """Test if a feed URL is accessible with proper error handling"""
        # For Twitter, use the EXACT SAME synchronous approach as standalone
        if platform == "twitter":
            return await self.test_twitter_feed(feed_name)

        # For other platforms, use optimized method with shorter timeout
        headers = self.get_chromium_headers()

        if platform == "reddit":
            headers['User-Agent'] = 'Mozilla/5.0 (compatible; SocialFeedBot/1.0)'

        async with aiohttp.ClientSession() as session:
            try:
                print(f"🔍 Testing feed URL: {feed_url}")
                # Reduced timeout from 15 to 8 seconds for faster response
                async with session.get(feed_url, timeout=8, headers=headers, allow_redirects=True) as response:
                    print(f"📡 Response status: {response.status}")

                    if response.status == 200:
                        # Read only first 10KB to check if it's RSS (faster)
                        text = await response.text()

                        # Quick check for RSS tags
                        if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml']):
                            # Only parse if it's a valid RSS
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
                            print("❌ Not a valid RSS feed")
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

        # For YouTube, get channel ID using scraper
        actual_feed_name = self.feed_name
        display_name = self.feed_name

        if self.platform == "youtube":
            # Get channel ID using the scraper
            channel_id = await asyncio.get_event_loop().run_in_executor(
                None, self.youtube_scraper.get_channel_info, self.feed_name
            )

            if channel_id:
                actual_feed_name = channel_id
                print(f"✅ Got channel ID: {actual_feed_name} for {self.feed_name}")
            else:
                embed = discord.Embed(
                    title="❌ YouTube Channel Not Found",
                    description=f"Could not find YouTube channel: `{self.feed_name}`\n\n**Tips:**\n• Make sure the channel exists\n• Try using the channel ID instead of name\n• Channel IDs start with 'UC' and are 24 characters long",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # Test the feed with timeout protection
        try:
            feed_url = self.generate_feed_url(self.platform, actual_feed_name)
            if not feed_url:
                embed = discord.Embed(
                    title="❌ Error",
                    description="Could not generate feed URL.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Add a timeout for the entire testing process
            success, result = await asyncio.wait_for(
                self.test_feed_url(feed_url, self.platform, actual_feed_name),
                timeout=10.0  # 10 second timeout for entire test
            )

            if not success:
                embed = discord.Embed(
                    title="❌ Feed Error",
                    description=f"Could not access feed: {result}",
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
            if test_feed and test_feed.entries:
                latest_post = test_feed.entries[0]
                latest_post_id = latest_post.id if hasattr(latest_post, 'id') else latest_post.link
                if hasattr(latest_post, 'published_parsed') and latest_post.published_parsed:
                    latest_post_time = datetime(*latest_post.published_parsed[:6])

            # Generate feed URL for database
            feed_url = self.generate_feed_url(self.platform, actual_feed_name)

            # Save to database
            try:
                async with aiosqlite.connect(db_path) as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO SocialFeed(guild_id, channel_id, platform, feed_name, feed_url, last_post_id, last_post_time, last_check_time, working_instance, service_type, mention_text, display_name, channel_data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (interaction.guild.id, interaction.channel.id, self.platform, actual_feed_name, feed_url, latest_post_id, latest_post_time, datetime.now(), working_instance, service_type, self.mention_text, display_name, None)
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

                embed.add_field(
                    name="⚡ Service",
                    value=f"**{service_type.title()}** • `{working_instance}`",
                    inline=True
                )

                embed.set_footer(text="🚀 Social Feed System • Updates every 3 minutes", icon_url=DISCORD_ICON)
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                embed = discord.Embed(
                    title="❌ Database Error",
                    description=f"An error occurred while saving the feed: {str(e)}",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)

        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="⏰ Timeout Error",
                description="Feed testing took too long. The service might be slow or unavailable.",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        except Exception as e:
            embed = discord.Embed(
                title="❌ Unexpected Error",
                description=f"An unexpected error occurred: {str(e)}",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

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

    def create_twitter_message(self, tweet: feedparser.FeedParserDict, feed_name: str) -> str:
        """Create Twitter message with enhanced link"""
        enhanced_url = FxEmbed.convert_twitter_url(
            tweet.link,
            TWITTER_CONFIG["FXEMBED_MODE"]
        )

        username = feed_name.lstrip('@')
        message = f"New Post From **[@{username}]({enhanced_url})**"
        return message

    def create_youtube_message(self, video: feedparser.FeedParserDict, display_name: str) -> str:
        """Create YouTube message with direct link and channel name"""
        # Use direct YouTube link - Discord will auto-embed it
        message = f"New Video From **[@{display_name}]({video.link})**"
        return message

    def create_reddit_message(self, post: feedparser.FeedParserDict, feed_name: str) -> str:
        """Create Reddit message with RxEmbed URL for proper embeds"""
        # Simply replace reddit.com with rxddit.com in the original URL
        enhanced_url = RxEmbed.convert_reddit_url(post.link)

        # Extract subreddit/user name from feed_name
        if feed_name.startswith('r/'):
            display_name = feed_name
        elif feed_name.startswith('u/') or feed_name.startswith('user/'):
            display_name = feed_name
        else:
            display_name = f"r/{feed_name}"

        message = f"New Post From **[{display_name}]({enhanced_url})**"
        return message

    async def fetch_twitter_feed(self, feed_name: str):
        """Fetch Twitter feed using EXACT SAME synchronous approach as standalone"""
        # Use EXACT SAME synchronous approach as standalone
        return await asyncio.get_event_loop().run_in_executor(
            None, TwitterMonitor.fetch_latest_tweet, feed_name
        )

    async def fetch_feed_with_fallback(self, feed_url, platform, feed_name):
        """Fetch feed with fallback to other services and instances - OPTIMIZED"""
        if platform == "twitter":
            # Use EXACT SAME synchronous approach for Twitter
            tweet = await self.fetch_twitter_feed(feed_name)
            if tweet:
                return type('MockFeed', (), {'entries': [tweet]})(), "direct", "nitter"
            return None, "direct", "nitter"

        # For other platforms, use optimized approach
        headers = self.get_chromium_headers()

        if platform == "reddit":
            headers['User-Agent'] = 'Mozilla/5.0 (compatible; SocialFeedBot/1.0)'

        # Try current instance first with shorter timeout
        try:
            async with self.session.get(feed_url, timeout=10, headers=headers, allow_redirects=True) as response:
                if response.status == 200:
                    text = await response.text()
                    # Quick RSS check
                    if any(tag in text.lower() for tag in ['<rss', '<feed', '<?xml']):
                        feed = feedparser.parse(text)
                        if not hasattr(feed, 'bozo') or not feed.bozo:
                            if feed.entries:
                                return feed, "direct", "reddit"
        except (asyncio.TimeoutError, aiohttp.ClientError):
            pass  # Silently continue to next instance
        except Exception as e:
            print(f"❌ Error fetching feed {feed_url}: {e}")

        return None, "direct", "reddit"

    async def send_embed_message(self, channel, message: str, platform: str):
        """Send message with proper embedding support"""
        try:
            # For better embedding, send the URL separately or in a clean way
            if platform == "reddit":
                # Extract URL from message for testing
                url_match = re.search(r'\((https?://[^)]+)\)', message)
                if url_match:
                    reddit_url = url_match.group(1)
                    # Test if it's an rxddit URL
                    if 'rxddit.com' in reddit_url:
                        # Send the rxddit URL separately to ensure embedding
                        await channel.send(message)
                        return

            # Default send for other platforms
            await channel.send(message)

        except discord.HTTPException as e:
            print(f"Error sending message: {e}")
            # Fallback: try sending just the URL
            if platform == "reddit":
                url_match = re.search(r'\((https?://[^)]+)\)', message)
                if url_match:
                    await channel.send(url_match.group(1))

    @tasks.loop(seconds=180)  # Changed to 3 minutes (180 seconds)
    async def check_feeds(self):
        """Check all feeds for new posts - OPTIMIZED"""
        if self.is_checking:
            return

        self.is_checking = True
        try:
            async with self.db.execute("SELECT guild_id, channel_id, platform, feed_name, feed_url, last_post_id, working_instance, service_type, mention_text, display_name FROM SocialFeed") as cursor:
                feeds = await cursor.fetchall()

            for guild_id, channel_id, platform, feed_name, feed_url, last_post_id, working_instance, service_type, mention_text, display_name in feeds:
                try:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        continue

                    # Check if bot has permission to embed links
                    if not channel.permissions_for(guild.me).embed_links:
                        print(f"❌ Bot lacks 'Embed Links' permission in {channel.name}")
                        continue

                    # Use display name if available
                    actual_display_name = display_name if display_name else feed_name

                    # Fetch feed based on platform
                    feed, new_instance, new_service_type = await self.fetch_feed_with_fallback(feed_url, platform, feed_name)

                    if not feed or not feed.entries:
                        continue

                    latest_post = feed.entries[0]
                    current_post_id = latest_post.id if hasattr(latest_post, 'id') else latest_post.link

                    if current_post_id != last_post_id:
                        # Create message based on platform
                        if platform == "twitter":
                            message = self.create_twitter_message(latest_post, feed_name)
                        elif platform == "youtube":
                            message = self.create_youtube_message(latest_post, actual_display_name)
                        elif platform == "reddit":
                            message = self.create_reddit_message(latest_post, feed_name)

                        # Add mention if available
                        if mention_text:
                            full_message = f"{mention_text} {message}"
                        else:
                            full_message = message

                        # Send the message with proper embedding support
                        await self.send_embed_message(channel, full_message, platform)

                        # Update database
                        post_time = None
                        if hasattr(latest_post, 'published_parsed') and latest_post.published_parsed:
                            post_time = datetime(*latest_post.published_parsed[:6])

                        async with self.db.execute(
                            "UPDATE SocialFeed SET last_post_id = ?, last_post_time = ?, last_check_time = ?, working_instance = ?, service_type = ? WHERE guild_id = ? AND feed_name = ?",
                            (current_post_id, post_time, datetime.now(), new_instance or working_instance, new_service_type or service_type, guild_id, feed_name)
                        ):
                            await self.db.commit()

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
        """Get the last posted content from a feed - OPTIMIZED"""
        await ctx.defer(ephemeral=True)

        try:
            async with asyncio.timeout(15.0):
                # Search by display_name first, then by feed_name
                async with self.db.execute(
                    "SELECT platform, feed_name, feed_url, last_post_id, last_post_time, working_instance, service_type, mention_text, display_name FROM SocialFeed WHERE guild_id = ? AND (display_name = ? OR feed_name = ?)",
                    (ctx.guild.id, feed_name, feed_name)
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

                platform, feed_name_db, feed_url, last_post_id, last_post_time, working_instance, service_type, mention_text, display_name = feed

                # Use display name if available
                actual_display_name = display_name if display_name else feed_name_db

                if platform == "twitter":
                    tweet = await self.fetch_twitter_feed(feed_name_db)
                    if not tweet:
                        embed = discord.Embed(
                            title="❌ No Posts Found",
                            description="Could not fetch feed or no posts found.",
                            color=0xff0000
                        )
                        await ctx.send(embed=embed, ephemeral=True)
                        return

                    message = self.create_twitter_message(tweet, feed_name_db)
                    await ctx.send(message, ephemeral=True)

                elif platform == "youtube":
                    feed_data, _, _ = await self.fetch_feed_with_fallback(feed_url, platform, feed_name_db)

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

                    message = self.create_youtube_message(last_post, actual_display_name)
                    await ctx.send(message, ephemeral=True)

                elif platform == "reddit":
                    feed_data, _, _ = await self.fetch_feed_with_fallback(feed_url, platform, feed_name_db)

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

                    message = self.create_reddit_message(last_post, feed_name_db)
                    await ctx.send(message, ephemeral=True)

        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="⏰ Timeout Error",
                description="The operation took too long. Please try again later.",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred: {str(e)}",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="socialfeed_latest", description="Get the latest post from a feed")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def latest_feed(self, ctx, feed_name: str):
        """Get the latest post from a feed to test it - OPTIMIZED"""
        await ctx.defer(ephemeral=True)

        try:
            async with asyncio.timeout(15.0):
                # Search by display_name first, then by feed_name
                async with self.db.execute(
                    "SELECT platform, feed_name, feed_url, last_post_id, last_check_time, working_instance, service_type, mention_text, display_name FROM SocialFeed WHERE guild_id = ? AND (display_name = ? OR feed_name = ?)",
                    (ctx.guild.id, feed_name, feed_name)
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

                platform, feed_name_db, feed_url, last_post_id, last_check_time, working_instance, service_type, mention_text, display_name = feed

                # Use display name if available
                actual_display_name = display_name if display_name else feed_name_db

                if platform == "twitter":
                    tweet = await self.fetch_twitter_feed(feed_name_db)
                    if not tweet:
                        embed = discord.Embed(
                            title="❌ Test Failed",
                            description="Could not fetch feed or no posts found.",
                            color=0xff0000
                        )
                        await ctx.send(embed=embed, ephemeral=True)
                        return

                    message = f"🧪 **TEST -** " + self.create_twitter_message(tweet, feed_name_db)
                    await ctx.send(message, ephemeral=True)

                elif platform == "youtube":
                    feed_data, _, _ = await self.fetch_feed_with_fallback(feed_url, platform, feed_name_db)

                    if not feed_data or not feed_data.entries:
                        embed = discord.Embed(
                            title="❌ Test Failed",
                            description="Could not fetch feed or no posts found.",
                            color=0xff0000
                        )
                        await ctx.send(embed=embed, ephemeral=True)
                        return

                    latest_post = feed_data.entries[0]

                    message = f"🧪 **TEST -** " + self.create_youtube_message(latest_post, actual_display_name)
                    await ctx.send(message, ephemeral=True)

                elif platform == "reddit":
                    feed_data, _, _ = await self.fetch_feed_with_fallback(feed_url, platform, feed_name_db)

                    if not feed_data or not feed_data.entries:
                        embed = discord.Embed(
                            title="❌ Test Failed",
                            description="Could not fetch feed or no posts found.",
                            color=0xff0000
                        )
                        await ctx.send(embed=embed, ephemeral=True)
                        return

                    latest_post = feed_data.entries[0]

                    message = f"🧪 **TEST -** " + self.create_reddit_message(latest_post, feed_name_db)
                    await ctx.send(message, ephemeral=True)

        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="⏰ Timeout Error",
                description="The operation took too long. Please try again later.",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred: {str(e)}",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="socialfeed_remove", description="Remove a social media feed")
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def remove_feed(self, ctx, feed_name: str):
        """Remove a social media feed"""
        await ctx.defer(ephemeral=True)

        # Search by display_name first, then by feed_name
        async with self.db.execute(
            "DELETE FROM SocialFeed WHERE guild_id = ? AND (display_name = ? OR feed_name = ?)",
            (ctx.guild.id, feed_name, feed_name)
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
                title=f"📰 Your Social Feeds ({len(rows)} total)",
                color=NEPAL_BLUE,
                timestamp=datetime.utcnow()
            )

            for platform, feed_name, channel_id, last_post_time, last_check_time, working_instance, service_type, mention_text, display_name in rows:
                platform_emojis = {"twitter": "🐦", "youtube": "📺", "reddit": "🤖"}
                emoji = platform_emojis.get(platform, "📰")

                # Use display name if available, otherwise use feed name
                actual_display_name = display_name if display_name else feed_name

                # Create field value with both names
                field_value = f"**Platform:** {platform.title()}\n"
                field_value += f"**Feed Name:** `{feed_name}`\n"
                if display_name and display_name != feed_name:
                    field_value += f"**Display Name:** `{display_name}`\n"
                field_value += f"**Channel:** <#{channel_id}>"

                if service_type:
                    field_value += f"\n**Service:** {service_type}"

                if mention_text:
                    field_value += f"\n**Mentions:** {len(mention_text.split())} role(s)"

                embed.add_field(
                    name=f"{emoji} {actual_display_name}",
                    value=field_value,
                    inline=False
                )

            embed.set_footer(text="🔄 Updates every 3 minutes • Use /socialfeed_remove to delete feeds")
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
