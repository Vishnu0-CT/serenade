import asyncio
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

# Load opus for voice support
if not discord.opus.is_loaded():
    OPUS_PATHS = [
        "/opt/homebrew/lib/libopus.dylib",  # Apple Silicon
        "/usr/local/lib/libopus.dylib",      # Intel Mac
    ]
    for path in OPUS_PATHS:
        if os.path.exists(path):
            try:
                discord.opus.load_opus(path)
                print(f"Loaded opus from {path}")
                break
            except Exception as e:
                print(f"Failed to load opus from {path}: {e}")

    if not discord.opus.is_loaded():
        print("WARNING: Opus not loaded - voice will not work!")

from src.clients.spotify_scraper import SpotifyScraperClient
from src.clients.youtube import YouTubeClient
from src.clients.ytmusic import YTMusicClient
from src.music.player import PlayerManager
from src.music.queue import QueueManager
from src.resolver import Resolver
from src.ui.embeds import (
    added_to_queue_embed,
    error_embed,
    now_playing_embed,
    playlist_added_embed,
    queue_embed,
)

load_dotenv()


class MusicBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states = True
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

        # Initialize clients
        self.ytmusic = YTMusicClient()
        self.youtube = YouTubeClient()
        self.spotify = SpotifyScraperClient()

        # Create resolver with all clients
        self.resolver = Resolver(
            ytmusic=self.ytmusic,
            youtube=self.youtube,
            spotify=self.spotify,
        )

        self.queues = QueueManager()
        self.players = PlayerManager(self.youtube)

    async def setup_hook(self):
        # Guild-specific sync is instant; global sync can take up to an hour
        test_guild_id = os.getenv("TEST_GUILD_ID")
        if test_guild_id:
            guild = discord.Object(id=int(test_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


bot = MusicBot()


async def ensure_voice(interaction: discord.Interaction) -> discord.VoiceClient | None:
    """Ensure the bot is in the user's voice channel. Returns VoiceClient or None."""
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message(
            embed=error_embed("You must be in a voice channel."),
            ephemeral=True,
        )
        return None

    user_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        voice_client = await user_channel.connect()
    elif voice_client.channel != user_channel:
        await voice_client.move_to(user_channel)

    return voice_client


async def _stream_playlist_to_queue(
    resolver: Resolver,
    playlist_type: str,  # "spotify" or "youtube"
    url: str,
    queue,
    player,
    requested_by: str,
    interaction: discord.Interaction,
):
    """Background task: resolve playlist tracks and add to queue as they resolve."""
    iterator = (
        resolver.iter_spotify_playlist(url)
        if playlist_type == "spotify"
        else resolver.iter_youtube_playlist(url)
    )

    tracks_added = []
    first_track = True

    # Wrap blocking next() call to run in thread pool
    def get_next_track():
        try:
            return next(iterator)
        except StopIteration:
            return None

    while True:
        # Run blocking I/O in thread so event loop stays responsive
        track = await asyncio.to_thread(get_next_track)
        if track is None:
            break

        track.requested_by = requested_by
        queue.add(track)
        tracks_added.append(track)

        # Start playing on first track
        if first_track and not player.is_playing():
            await player.play_next()
            first_track = False

    # Send summary when done
    if tracks_added:
        await interaction.followup.send(embed=playlist_added_embed(tracks_added, 0))


@bot.tree.command(name="play", description="Play a song from a search query or URL")
@app_commands.describe(query="Song name, Spotify URL, or YouTube URL")
async def play(interaction: discord.Interaction, query: str):
    voice_client = await ensure_voice(interaction)
    if not voice_client:
        return

    await interaction.response.defer()

    guild_id = interaction.guild_id
    queue = bot.queues.get(guild_id)

    # Helper to ensure player exists
    def get_or_create_player():
        player = bot.players.get(guild_id)
        if not player:

            def on_disconnect():
                bot.players.remove(guild_id)
                bot.queues.remove(guild_id)

            player = bot.players.create(
                guild_id=guild_id,
                voice_client=voice_client,
                queue=queue,
                text_channel=interaction.channel,
                on_disconnect=on_disconnect,
            )
        return player

    # Detect playlist URLs and stream them
    if "open.spotify.com/playlist" in query or "spotify:playlist:" in query:
        player = get_or_create_player()
        await interaction.followup.send("Loading Spotify playlist...")
        asyncio.create_task(
            _stream_playlist_to_queue(
                bot.resolver,
                "spotify",
                query,
                queue,
                player,
                interaction.user.display_name,
                interaction,
            )
        )
        return

    if "youtube.com/playlist" in query:
        player = get_or_create_player()
        await interaction.followup.send("Loading YouTube playlist...")
        asyncio.create_task(
            _stream_playlist_to_queue(
                bot.resolver,
                "youtube",
                query,
                queue,
                player,
                interaction.user.display_name,
                interaction,
            )
        )
        return

    # Resolve the query to track(s)
    try:
        tracks = bot.resolver.resolve(query)
    except NotImplementedError as e:
        await interaction.followup.send(embed=error_embed(str(e)))
        return
    except ValueError as e:
        await interaction.followup.send(embed=error_embed(str(e)))
        return
    except Exception:
        await interaction.followup.send(embed=error_embed("Could not find that song."))
        return

    # Set requested_by for all tracks and add to queue
    first_position = None
    for track in tracks:
        track.requested_by = interaction.user.display_name
        position = queue.add(track)
        if first_position is None:
            first_position = position

    # Get or create player
    player = get_or_create_player()

    # Start playing if not already
    if not player.is_playing():
        played_track = await player.play_next(notify=False)
        if played_track:
            await interaction.followup.send(embed=now_playing_embed(played_track))
        else:
            await interaction.followup.send(embed=error_embed("Failed to play track."))
    else:
        # Show the first track added (for single tracks or first of playlist)
        await interaction.followup.send(embed=added_to_queue_embed(tracks[0], first_position))


@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    player = bot.players.get(interaction.guild_id)
    if not player or not player.is_playing():
        await interaction.response.send_message(
            embed=error_embed("Nothing is playing."),
            ephemeral=True,
        )
        return

    current = bot.queues.get(interaction.guild_id).current
    player.skip()
    await interaction.response.send_message(
        f"Skipped **{current.title}** by {current.artist}" if current else "Skipped."
    )


@bot.tree.command(name="stop", description="Stop playback and clear the queue")
async def stop(interaction: discord.Interaction):
    player = bot.players.get(interaction.guild_id)
    if not player:
        await interaction.response.send_message(
            embed=error_embed("Nothing is playing."),
            ephemeral=True,
        )
        return

    await player.stop()
    bot.players.remove(interaction.guild_id)
    bot.queues.remove(interaction.guild_id)
    await interaction.response.send_message("Stopped playback and cleared the queue.")


@bot.tree.command(name="pause", description="Pause playback")
async def pause(interaction: discord.Interaction):
    player = bot.players.get(interaction.guild_id)
    if not player:
        await interaction.response.send_message(
            embed=error_embed("Nothing is playing."),
            ephemeral=True,
        )
        return

    if player.pause():
        await interaction.response.send_message("Paused.")
    else:
        await interaction.response.send_message(
            embed=error_embed("Nothing is playing."),
            ephemeral=True,
        )


@bot.tree.command(name="resume", description="Resume playback")
async def resume(interaction: discord.Interaction):
    player = bot.players.get(interaction.guild_id)
    if not player:
        await interaction.response.send_message(
            embed=error_embed("Nothing to resume."),
            ephemeral=True,
        )
        return

    if player.resume():
        await interaction.response.send_message("Resumed.")
    else:
        await interaction.response.send_message(
            embed=error_embed("Nothing is paused."),
            ephemeral=True,
        )


@bot.tree.command(name="queue", description="Show the current queue")
async def show_queue(interaction: discord.Interaction):
    queue = bot.queues.get(interaction.guild_id)
    tracks = queue.get_list()
    current = queue.current
    await interaction.response.send_message(embed=queue_embed(tracks, current))


@bot.tree.command(name="clear", description="Clear the queue (keeps current song playing)")
async def clear(interaction: discord.Interaction):
    queue = bot.queues.get(interaction.guild_id)
    queue.clear()
    await interaction.response.send_message("Queue cleared.")


@bot.tree.command(name="shuffle", description="Toggle shuffle mode")
@app_commands.describe(enabled="Turn shuffle on or off")
async def shuffle(interaction: discord.Interaction, enabled: bool):
    queue = bot.queues.get(interaction.guild_id)
    queue.shuffle = enabled
    status = "enabled" if enabled else "disabled"
    await interaction.response.send_message(f"Shuffle {status}.")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is not set")
    bot.run(token)


if __name__ == "__main__":
    main()
