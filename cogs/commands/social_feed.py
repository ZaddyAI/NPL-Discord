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
from utils.Tools import *

db_folder = 'db'
db_file = 'social_feed.db'
db_path = os.path.join(db_folder, db_file)

# Nepal flag blue color
NEPAL_BLUE = 0x003893

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
                                PRIMARY KEY (guild_id, feed_name)
                            )''')
        await db.commit()

class PlatformDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Twitter/X", value="twitter", emoji="🐦", description="Twitter/X feeds"),
            discord.SelectOption(label="YouTube", value="youtube", emoji="📺", description="YouTube channels"),
            discord.SelectOption(label="Reddit", value="reddit", emoji="🤖", description="Reddit subreddits/users"),
        ]
        super().__init__(placeholder="Select a platform...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.view.platform = self.values[0]
        await interaction.response.send_modal(AddFeedModal(self.view))

class AddFeedModal(discord.ui.Modal, title="Add Social Feed"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.timeout = 300

    username = discord.ui.TextInput(
        label="Username / Channel ID / Subreddit",
        placeholder="e.g., CricketNep, UCxxx, r/nepal",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.view.feed_name = self.username.value.strip()
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
        self.add_item(PlatformDropdown())

    async def on_timeout(self):
        pass

    def get_nitter_instances(self):
        """Get list of working Nitter instances with fallbacks"""
        return [
            "nitter.net",
            "nitter.privacydev.net",
            "nitter.poast.org",
            "nitter.fly.dev",
            "nitter.lacontrevoie.fr",
            "nitter.tedomum.net",
            "nitter.fdn.fr",
            "nitter.1d4.us",
            "nitter.kavin.rocks",
            "nitter.unixfox.eu"
        ]

    def generate_feed_url(self, platform, feed_name, instance=None):
        """Generate appropriate RSS feed URL based on platform"""
        if platform == "twitter":
            clean_name = feed_name.lstrip('@')
            if instance:
                return f"https://{instance}/{clean_name}/rss"
            else:
                # Try multiple instances until one works
                instances = self.get_nitter_instances()
                instance = random.choice(instances)
                return f"https://{instance}/{clean_name}/rss"
        elif platform == "youtube":
            if feed_name.startswith('@'):
                return f"https://www.youtube.com/feeds/videos.xml?channel_id={feed_name.lstrip('@')}"
            else:
                return f"https://www.youtube.com/feeds/videos.xml?channel_id={feed_name}"
        elif platform == "reddit":
            clean_name = feed_name.lower().strip()

            if clean_name.startswith('r/'):
                subreddit = clean_name[2:].strip()
                return f"https://www.reddit.com/r/{subreddit}/.rss"
            elif clean_name.startswith('u/') or clean_name.startswith('user/'):
                username = clean_name[2:] if clean_name.startswith('u/') else clean_name[5:]
                return f"https://www.reddit.com/user/{username}/.rss"
            elif clean_name.startswith('/r/'):
                subreddit = clean_name[3:].strip()
                return f"https://www.reddit.com/r/{subreddit}/.rss"
            elif clean_name.startswith('/u/'):
                username = clean_name[3:].strip()
                return f"https://www.reddit.com/user/{username}/.rss"
            else:
                return f"https://www.reddit.com/r/{clean_name}/.rss"
        return None

    def validate_feed_name(self, platform, feed_name):
        """Validate feed name format"""
        if platform == "reddit":
            clean_name = re.sub(r'[^a-zA-Z0-9_\-/]', '', feed_name)

            if not clean_name:
                return False, "Invalid Reddit name format"

            if '/' in clean_name and not clean_name.startswith(('r/', 'u/', '/r/', '/u/')):
                parts = clean_name.split('/')
                if len(parts) == 2 and parts[0].isdigit():
                    return True, f"r/{parts[1]}"

        return True, feed_name

    async def test_feed_url(self, feed_url, platform):
        """Test if a feed URL is accessible with multiple fallbacks"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }

        if platform == "twitter":
            headers.update({
                'Referer': 'https://nitter.net/',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
            })

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(feed_url, timeout=15, headers=headers) as response:
                    if response.status == 200:
                        text = await response.text()
                        feed = feedparser.parse(text)

                        if hasattr(feed, 'bozo') and feed.bozo:
                            return False, f"Invalid RSS feed format: {feed.bozo_exception if hasattr(feed, 'bozo_exception') else 'Unknown error'}"

                        if not feed.entries:
                            return False, "Feed has no posts"

                        return True, feed
                    else:
                        return False, f"HTTP {response.status}: {response.reason}"
            except asyncio.TimeoutError:
                return False, "Request timeout"
            except aiohttp.ClientError as e:
                return False, f"Connection error: {str(e)}"
            except Exception as e:
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

        # For Twitter, try multiple instances if first one fails
        feed_url = None
        test_feed = None
        working_instance = None

        if self.platform == "twitter":
            instances = self.get_nitter_instances()
            successful_instances = []

            for instance in instances:
                test_url = f"https://{instance}/{self.feed_name.lstrip('@')}/rss"
                success, result = await self.test_feed_url(test_url, self.platform)
                if success:
                    successful_instances.append(instance)
                    if not feed_url:  # Use the first successful one
                        feed_url = test_url
                        test_feed = result
                        working_instance = instance

            if not successful_instances:
                # All instances failed
                embed = discord.Embed(
                    title="❌ Twitter Feed Error",
                    description="All Nitter instances are currently unavailable. Please try again later.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Store successful instances for future reference
            self.successful_instances = successful_instances
        else:
            feed_url = self.generate_feed_url(self.platform, self.feed_name)
            if not feed_url:
                embed = discord.Embed(
                    title="❌ Error",
                    description="Could not generate feed URL.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            success, result = await self.test_feed_url(feed_url, self.platform)
            if not success:
                embed = discord.Embed(
                    title="❌ Feed Error",
                    description=f"Could not access feed: {result}\n\n**URL:** {feed_url}",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            test_feed = result
            working_instance = "direct"  # For non-Twitter platforms

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
                    "INSERT OR REPLACE INTO SocialFeed(guild_id, channel_id, platform, feed_name, feed_url, last_post_id, last_post_time, last_check_time, working_instance) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (interaction.guild.id, interaction.channel.id, self.platform, self.feed_name, feed_url, latest_post_id, latest_post_time, datetime.now(), working_instance)
                )
                await db.commit()

            platform_emojis = {
                "twitter": "🐦", "youtube": "📺", "reddit": "🤖"
            }

            description = (
                f"**Platform:** {platform_emojis.get(self.platform, '📰')} {self.platform.title()}\n"
                f"**Username:** `{self.feed_name}`\n"
                f"**Channel:** {interaction.channel.mention}\n"
            )

            if self.platform == "twitter" and hasattr(self, 'successful_instances'):
                description += f"**Working Instances:** {len(self.successful_instances)} found\n"
                description += f"**Primary Instance:** `{working_instance}`\n\n"
            else:
                description += f"**Instance:** `{working_instance}`\n\n"

            description += "New posts will be automatically posted to this channel!"

            embed = discord.Embed(
                title="✅ Feed Added Successfully",
                description=description,
                color=NEPAL_BLUE
            )
            embed.set_footer(text="Social Feed System • Updates every 30 seconds")
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

    def extract_media_urls(self, platform, entry):
        """Extract image and video URLs from feed entry"""
        media_urls = []

        if platform == "reddit":
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                for thumb in entry.media_thumbnail:
                    if hasattr(thumb, 'url') and thumb.url:
                        media_urls.append(thumb.url)

            if hasattr(entry, 'media_content') and entry.media_content:
                for media in entry.media_content:
                    if hasattr(media, 'url') and media.url:
                        if any(ext in media.url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                            media_urls.append(media.url)
                        elif any(ext in media.url.lower() for ext in ['.mp4', '.mov', '.avi', '.webm']):
                            media_urls.append(media.url)

            if hasattr(entry, 'summary') and entry.summary:
                img_matches = re.findall(r'src="([^"]+\.(?:jpg|jpeg|png|gif|webp))"', entry.summary)
                media_urls.extend(img_matches)

        elif platform == "twitter":
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                for thumb in entry.media_thumbnail:
                    if hasattr(thumb, 'url') and thumb.url:
                        media_urls.append(thumb.url)

            if hasattr(entry, 'description') and entry.description:
                img_matches = re.findall(r'src="([^"]+\.(?:jpg|jpeg|png|gif|webp))"', entry.description)
                media_urls.extend(img_matches)

        elif platform == "youtube":
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                for thumb in entry.media_thumbnail:
                    if hasattr(thumb, 'url') and thumb.url:
                        media_urls.append(thumb.url)

            if hasattr(entry, 'yt_videoid'):
                media_urls.append(f"https://www.youtube.com/watch?v={entry.yt_videoid}")

        return list(set(media_urls))

    def create_post_embed(self, platform, feed_name, post_data, is_test=False):
        """Create a beautiful embed for social media posts"""
        embed = discord.Embed(color=NEPAL_BLUE, timestamp=datetime.utcnow())

        platform_configs = {
            "twitter": {
                "emoji": "🐦",
                "color": NEPAL_BLUE,
                "author_format": "{} on Twitter"
            },
            "youtube": {
                "emoji": "📺",
                "color": NEPAL_BLUE,
                "author_format": "{} on YouTube"
            },
            "reddit": {
                "emoji": "🤖",
                "color": NEPAL_BLUE,
                "author_format": "{} on Reddit"
            }
        }

        config = platform_configs.get(platform, platform_configs["twitter"])

        title = post_data.get('title', 'New Post')
        if len(title) > 200:
            title = title[:197] + "..."

        if is_test:
            embed.title = f"🧪 TEST: {config['emoji']} {title}"
        else:
            embed.title = f"{config['emoji']} {title}"

        embed.url = post_data.get('link', '')

        description = post_data.get('summary', post_data.get('description', ''))
        if description:
            description = re.sub('<[^<]+?>', '', description)
            if len(description) > 500:
                description = description[:497] + "..."
            embed.description = description

        author = config['author_format'].format(feed_name)
        embed.set_author(name=author)

        media_urls = post_data.get('media_urls', [])
        if media_urls:
            image_url = None
            for url in media_urls:
                if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    image_url = url
                    break

            if image_url:
                embed.set_image(url=image_url)

            if platform == "youtube":
                for url in media_urls:
                    if 'ytimg.com' in url or 'youtube.com' in url:
                        embed.set_thumbnail(url=url)
                        break
            elif platform == "reddit":
                embed.set_thumbnail(url="https://www.redditstatic.com/icon.png")
            elif platform == "twitter":
                embed.set_thumbnail(url="https://abs.twimg.com/favicons/twitter.2.ico")
        else:
            if platform == "youtube":
                embed.set_thumbnail(url="https://www.youtube.com/s/desktop/5c6daf13/img/favicon_144x144.png")
            elif platform == "reddit":
                embed.set_thumbnail(url="https://www.redditstatic.com/icon.png")
            elif platform == "twitter":
                embed.set_thumbnail(url="https://abs.twimg.com/favicons/twitter.2.ico")

        if post_data.get('published'):
            try:
                published = post_data['published']
                if hasattr(published, 'strftime'):
                    embed.add_field(name="Posted", value=f"<t:{int(published.timestamp())}:R>", inline=True)
            except:
                pass

        if media_urls:
            image_count = sum(1 for url in media_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']))
            video_count = sum(1 for url in media_urls if any(ext in url.lower() for ext in ['.mp4', '.mov', '.avi', '.webm']))

            if image_count > 0 or video_count > 0:
                media_text = []
                if image_count > 0:
                    media_text.append(f"{image_count} image{'s' if image_count > 1 else ''}")
                if video_count > 0:
                    media_text.append(f"{video_count} video{'s' if video_count > 1 else ''}")

                if media_text:
                    embed.add_field(name="Media", value=", ".join(media_text), inline=True)

        if is_test:
            embed.set_footer(text=f"Test Feed • {platform.title()}")
        else:
            embed.set_footer(text=f"Social Feed • {platform.title()}")

        return embed, media_urls

    def get_nitter_instances(self):
        """Get list of working Nitter instances"""
        return [
            "nitter.net",
            "nitter.privacydev.net",
            "nitter.poast.org",
            "nitter.fly.dev",
            "nitter.lacontrevoie.fr",
            "nitter.tedomum.net",
            "nitter.fdn.fr",
            "nitter.1d4.us",
            "nitter.kavin.rocks",
            "nitter.unixfox.eu"
        ]

    async def fetch_feed_with_fallback(self, feed_url, platform, feed_name, current_instance=None):
        """Fetch feed with fallback to other instances if current one fails"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        if platform == "twitter":
            headers['Referer'] = 'https://nitter.net/'

        # Try current instance first
        try:
            async with self.session.get(feed_url, timeout=15, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    feed = feedparser.parse(text)

                    if hasattr(feed, 'bozo') and feed.bozo:
                        raise Exception(f"Feed parsing error: {feed.bozo_exception}")

                    if feed.entries:
                        return feed, current_instance
        except Exception as e:
            print(f"Current instance failed ({current_instance}): {e}")

        # If current instance fails and it's Twitter, try other instances
        if platform == "twitter":
            instances = self.get_nitter_instances()
            # Remove current instance from the list
            if current_instance in instances:
                instances.remove(current_instance)

            for instance in instances:
                try:
                    new_feed_url = f"https://{instance}/{feed_name.lstrip('@')}/rss"
                    async with self.session.get(new_feed_url, timeout=10, headers=headers) as response:
                        if response.status == 200:
                            text = await response.text()
                            feed = feedparser.parse(text)

                            if hasattr(feed, 'bozo') and feed.bozo:
                                continue

                            if feed.entries:
                                print(f"Switched to instance: {instance}")
                                return feed, instance
                except Exception as e:
                    print(f"Instance {instance} failed: {e}")
                    continue

        return None, current_instance

    async def fetch_feed(self, feed_url, platform=None, feed_name=None, current_instance=None):
        """Fetch and parse RSS feed with instance tracking"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            if platform == "twitter":
                headers['Referer'] = 'https://nitter.net/'

            async with self.session.get(feed_url, timeout=15, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    feed = feedparser.parse(text)

                    if hasattr(feed, 'bozo') and feed.bozo:
                        print(f"Feed parsing error for {feed_url}: {feed.bozo_exception}")
                        return None

                    return feed
                else:
                    print(f"HTTP {response.status} for feed: {feed_url}")
                    return None
        except asyncio.TimeoutError:
            print(f"Timeout fetching feed: {feed_url}")
            return None
        except Exception as e:
            print(f"Error fetching feed {feed_url}: {e}")
            return None

    @tasks.loop(seconds=60)
    async def check_feeds(self):
        """Check all feeds for new posts with instance fallback"""
        try:
            async with self.db.execute("SELECT guild_id, channel_id, platform, feed_name, feed_url, last_post_id, working_instance FROM SocialFeed") as cursor:
                feeds = await cursor.fetchall()

            for guild_id, channel_id, platform, feed_name, feed_url, last_post_id, working_instance in feeds:
                try:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        continue

                    # Use fallback system for Twitter feeds
                    if platform == "twitter":
                        feed, new_instance = await self.fetch_feed_with_fallback(feed_url, platform, feed_name, working_instance)

                        # Update instance if changed
                        if new_instance != working_instance and new_instance:
                            async with self.db.execute(
                                "UPDATE SocialFeed SET working_instance = ?, feed_url = ? WHERE guild_id = ? AND feed_name = ?",
                                (new_instance, f"https://{new_instance}/{feed_name.lstrip('@')}/rss", guild_id, feed_name)
                            ):
                                await self.db.commit()
                                working_instance = new_instance
                    else:
                        feed = await self.fetch_feed(feed_url)

                    if not feed or not feed.entries:
                        continue

                    latest_post = feed.entries[0]
                    current_post_id = latest_post.id if hasattr(latest_post, 'id') else latest_post.link

                    if current_post_id != last_post_id:
                        # Extract media URLs
                        media_urls = self.extract_media_urls(platform, latest_post)

                        post_data = {
                            'title': latest_post.title,
                            'link': latest_post.link,
                            'summary': getattr(latest_post, 'summary', ''),
                            'description': getattr(latest_post, 'description', ''),
                            'published': getattr(latest_post, 'published_parsed', None),
                            'media_thumbnail': getattr(latest_post, 'media_thumbnail', None),
                            'media_content': getattr(latest_post, 'media_content', None),
                            'media_urls': media_urls
                        }

                        # Create embed and get media URLs
                        embed, all_media_urls = self.create_post_embed(platform, feed_name, post_data)

                        try:
                            # Send the embed
                            message = await channel.send(embed=embed)

                            # Send additional images
                            image_urls = [url for url in all_media_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])]

                            for i, image_url in enumerate(image_urls[:3]):
                                try:
                                    embed = discord.Embed(color=NEPAL_BLUE)
                                    embed.set_image(url=image_url)
                                    embed.set_footer(text=f"Additional media {i+1}/{len(image_urls[:3])}")
                                    await channel.send(embed=embed)
                                except Exception as e:
                                    print(f"Error sending additional image: {e}")

                            post_time = None
                            if hasattr(latest_post, 'published_parsed') and latest_post.published_parsed:
                                post_time = datetime(*latest_post.published_parsed[:6])

                            # Update database
                            async with self.db.execute(
                                "UPDATE SocialFeed SET last_post_id = ?, last_post_time = ?, last_check_time = ?, working_instance = ? WHERE guild_id = ? AND feed_name = ?",
                                (current_post_id, post_time, datetime.now(), working_instance, guild_id, feed_name)
                            ):
                                await self.db.commit()

                        except discord.Forbidden:
                            print(f"No permission to send messages in {channel.name}")
                        except Exception as e:
                            print(f"Error sending message to {channel.name}: {e}")
                    else:
                        # Update last check time
                        async with self.db.execute(
                            "UPDATE SocialFeed SET last_check_time = ?, working_instance = ? WHERE guild_id = ? AND feed_name = ?",
                            (datetime.now(), working_instance, guild_id, feed_name)
                        ):
                            await self.db.commit()

                except Exception as e:
                    print(f"Error processing feed {feed_name} for guild {guild_id}: {e}")
                    continue

        except Exception as e:
            print(f"Error in check_feeds: {e}")

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
            title="📰 Add Social Feed",
            description="Select a platform from the dropdown below:",
            color=NEPAL_BLUE
        )
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
            "SELECT platform, feed_name, feed_url, last_post_id, last_post_time, working_instance FROM SocialFeed WHERE guild_id = ? AND feed_name = ?",
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

        platform, feed_name, feed_url, last_post_id, last_post_time, working_instance = feed

        # Use fallback system for fetching
        if platform == "twitter":
            feed_data, _ = await self.fetch_feed_with_fallback(feed_url, platform, feed_name, working_instance)
        else:
            feed_data = await self.fetch_feed(feed_url)

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

        # Extract media URLs for the test post
        media_urls = self.extract_media_urls(platform, last_post)

        post_data = {
            'title': last_post.title,
            'link': last_post.link,
            'summary': getattr(last_post, 'summary', ''),
            'description': getattr(last_post, 'description', ''),
            'published': getattr(last_post, 'published_parsed', None),
            'media_thumbnail': getattr(last_post, 'media_thumbnail', None),
            'media_content': getattr(last_post, 'media_content', None),
            'media_urls': media_urls
        }

        embed, all_media_urls = self.create_post_embed(platform, feed_name, post_data, is_test=True)

        # Add instance information
        if platform == "twitter" and working_instance:
            embed.add_field(
                name="Instance",
                value=f"`{working_instance}`",
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
                    name="Last Posted",
                    value=f"<t:{int(last_post_time.timestamp())}:R>",
                    inline=True
                )
        elif hasattr(last_post, 'published_parsed') and last_post.published_parsed:
            post_time = datetime(*last_post.published_parsed[:6])
            embed.add_field(
                name="Post Created",
                value=f"<t:{int(post_time.timestamp())}:R>",
                inline=True
            )

        embed.add_field(
            name="Post ID",
            value=f"`{last_post_id[:20]}...`" if last_post_id and len(last_post_id) > 20 else f"`{last_post_id}`",
            inline=True
        )

        await ctx.send(embed=embed, ephemeral=True)

        # Send additional media if available in test mode
        image_urls = [url for url in all_media_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])]
        for i, image_url in enumerate(image_urls[:2]):
            try:
                additional_embed = discord.Embed(color=NEPAL_BLUE)
                additional_embed.set_image(url=image_url)
                additional_embed.set_footer(text=f"Test Media {i+1}/{len(image_urls[:2])}")
                await ctx.send(embed=additional_embed, ephemeral=True)
            except Exception as e:
                print(f"Error sending test media: {e}")

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
            "SELECT platform, feed_name, feed_url, last_post_id, last_check_time, working_instance FROM SocialFeed WHERE guild_id = ? AND feed_name = ?",
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

        platform, feed_name, feed_url, last_post_id, last_check_time, working_instance = feed

        # Use fallback system for fetching
        if platform == "twitter":
            feed_data, new_instance = await self.fetch_feed_with_fallback(feed_url, platform, feed_name, working_instance)
        else:
            feed_data = await self.fetch_feed(feed_url)

        if not feed_data or not feed_data.entries:
            embed = discord.Embed(
                title="❌ Test Failed",
                description="Could not fetch feed or no posts found.",
                color=0xff0000
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        latest_post = feed_data.entries[0]

        # Extract media URLs for the latest post
        media_urls = self.extract_media_urls(platform, latest_post)

        post_data = {
            'title': latest_post.title,
            'link': latest_post.link,
            'summary': getattr(latest_post, 'summary', ''),
            'description': getattr(latest_post, 'description', ''),
            'published': getattr(latest_post, 'published_parsed', None),
            'media_thumbnail': getattr(latest_post, 'media_thumbnail', None),
            'media_content': getattr(latest_post, 'media_content', None),
            'media_urls': media_urls
        }

        embed, all_media_urls = self.create_post_embed(platform, feed_name, post_data, is_test=True)

        # Add instance information
        if platform == "twitter":
            current_instance = new_instance if new_instance else working_instance
            if current_instance:
                embed.add_field(
                    name="Instance",
                    value=f"`{current_instance}`",
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
                    name="Last Checked",
                    value=f"<t:{int(last_check_time.timestamp())}:R>",
                    inline=True
                )

        embed.add_field(
            name="Current Post ID",
            value=f"`{last_post_id[:20]}...`" if last_post_id and len(last_post_id) > 20 else f"`{last_post_id}`",
            inline=True
        )

        await ctx.send(embed=embed, ephemeral=True)

        # Send additional media if available in test mode
        image_urls = [url for url in all_media_urls if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])]
        for i, image_url in enumerate(image_urls[:2]):
            try:
                additional_embed = discord.Embed(color=NEPAL_BLUE)
                additional_embed.set_image(url=image_url)
                additional_embed.set_footer(text=f"Test Media {i+1}/{len(image_urls[:2])}")
                await ctx.send(embed=additional_embed, ephemeral=True)
            except Exception as e:
                print(f"Error sending test media: {e}")

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
                    title="🗑️ Feed Removed",
                    description=f"Successfully removed feed `{feed_name}`",
                    color=NEPAL_BLUE
                )
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
            msg = ""
            async with self.db.execute(
                "SELECT platform, feed_name, channel_id, last_post_time, last_check_time, working_instance FROM SocialFeed WHERE guild_id = ?",
                (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()
                for platform, feed_name, channel_id, last_post_time, last_check_time, working_instance in rows:
                    platform_emojis = {
                        "twitter": "🐦", "youtube": "📺", "reddit": "🤖"
                    }
                    emoji = platform_emojis.get(platform, "📰")

                    instance_info = ""
                    if platform == "twitter" and working_instance:
                        instance_info = f" • `{working_instance}`"

                    time_info = ""
                    if last_post_time:
                        if isinstance(last_post_time, str):
                            try:
                                last_post_time = datetime.fromisoformat(last_post_time.replace('Z', '+00:00'))
                            except:
                                last_post_time = None

                        if last_post_time and hasattr(last_post_time, 'timestamp'):
                            time_info = f" (Last post: <t:{int(last_post_time.timestamp())}:R>)"

                    if not time_info and last_check_time:
                        if isinstance(last_check_time, str):
                            try:
                                last_check_time = datetime.fromisoformat(last_check_time.replace('Z', '+00:00'))
                            except:
                                last_check_time = None

                        if last_check_time and hasattr(last_check_time, 'timestamp'):
                            time_info = f" (Last check: <t:{int(last_check_time.timestamp())}:R>)"

                    msg += f"{emoji} **{feed_name}** ({platform}){instance_info} → <#{channel_id}>{time_info}\n"

            if msg:
                embed = discord.Embed(
                    title="📰 Social Feeds",
                    description=msg,
                    color=NEPAL_BLUE
                )
                embed.set_footer(text=f"Total feeds: {len(rows)} • Updates every 60 seconds")
                await ctx.send(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(
                    title="📰 Social Feeds",
                    description="No social feeds configured. Use `/socialfeed` to get started!",
                    color=NEPAL_BLUE
                )
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
