import discord

from src.models.track import Track


def now_playing_embed(track: Track) -> discord.Embed:
    """Create an embed for the currently playing track."""
    embed = discord.Embed(
        title="Now Playing",
        description=f"**{track.title}**",
        color=discord.Color.green(),
    )
    embed.add_field(name="Artist", value=track.artist, inline=True)
    embed.add_field(name="Duration", value=track.duration_str, inline=True)

    if track.album_art_url:
        embed.set_thumbnail(url=track.album_art_url)

    # Build links based on available URLs
    if track.source_url and track.source_url != track.youtube_url:
        # Determine source label based on URL
        if "spotify" in track.source_url:
            source_label = "Spotify"
        elif "music.youtube.com" in track.source_url:
            source_label = "YT Music"
        else:
            source_label = "Source"
        embed.add_field(
            name="Links",
            value=f"[{source_label}]({track.source_url}) | [YouTube]({track.youtube_url})",
            inline=False,
        )
    else:
        embed.add_field(
            name="Links",
            value=f"[YouTube]({track.youtube_url})",
            inline=False,
        )

    embed.set_footer(text=f"Requested by {track.requested_by}")
    return embed


def added_to_queue_embed(track: Track, position: int) -> discord.Embed:
    """Create an embed for a track added to the queue."""
    embed = discord.Embed(
        title="Added to Queue",
        description=f"**{track.title}** by {track.artist}",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Position", value=str(position + 1), inline=True)
    embed.add_field(name="Duration", value=track.duration_str, inline=True)

    if track.album_art_url:
        embed.set_thumbnail(url=track.album_art_url)

    embed.set_footer(text=f"Requested by {track.requested_by}")
    return embed


def queue_embed(tracks: list[Track], current: Track | None) -> discord.Embed:
    """Create an embed showing the current queue."""
    embed = discord.Embed(
        title="Music Queue",
        color=discord.Color.purple(),
    )

    if current:
        embed.add_field(
            name="Now Playing",
            value=f"**{current.title}** by {current.artist} [{current.duration_str}]",
            inline=False,
        )

    if tracks:
        queue_text = "\n".join(
            f"`{i + 1}.` **{t.title}** by {t.artist} [{t.duration_str}]"
            for i, t in enumerate(tracks[:10])  # Show max 10 tracks
        )
        if len(tracks) > 10:
            queue_text += f"\n\n*...and {len(tracks) - 10} more*"
        embed.add_field(name="Up Next", value=queue_text, inline=False)
    elif not current:
        embed.description = "The queue is empty."

    total_tracks = len(tracks) + (1 if current else 0)
    embed.set_footer(text=f"{total_tracks} track(s) in queue")
    return embed


def error_embed(message: str) -> discord.Embed:
    """Create an error embed."""
    return discord.Embed(
        title="Error",
        description=message,
        color=discord.Color.red(),
    )


def playlist_added_embed(tracks: list[Track], failed_count: int = 0) -> discord.Embed:
    """Embed for playlist added to queue."""
    desc = f"**{len(tracks)} tracks** added to queue"
    if failed_count > 0:
        desc += f" ({failed_count} could not be resolved)"

    embed = discord.Embed(
        title="Playlist Loaded",
        description=desc,
        color=discord.Color.blue(),
    )

    # Total duration
    total_ms = sum(t.duration_ms for t in tracks)
    minutes = total_ms // 60000
    embed.add_field(name="Duration", value=f"{minutes}m", inline=True)

    # Preview first 5 tracks
    preview = "\n".join(f"`{i+1}.` {t.title}" for i, t in enumerate(tracks[:5]))
    if len(tracks) > 5:
        preview += f"\n*...and {len(tracks) - 5} more*"
    embed.add_field(name="Tracks", value=preview, inline=False)

    return embed
