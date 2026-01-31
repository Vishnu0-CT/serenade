from typing import Iterator

from src.clients.spotify_scraper import SpotifyScraperClient
from src.clients.youtube import YouTubeClient
from src.clients.ytmusic import YTMusicClient
from src.models.track import Track

MAX_PLAYLIST_TRACKS = 500


class Resolver:
    """Resolves any input (search query or URL) to playable Track(s)."""

    def __init__(
        self,
        ytmusic: YTMusicClient,
        youtube: YouTubeClient,
        spotify: SpotifyScraperClient,
    ):
        self.ytmusic = ytmusic
        self.youtube = youtube
        self.spotify = spotify

    def resolve(self, query: str) -> list[Track]:
        """
        Resolve a query to a list of tracks.

        Supports:
        - Natural language search (e.g., "never gonna give you up")
        - YouTube video URLs
        - YouTube Music URLs
        - Spotify track URLs

        Returns list (even for single track) to support playlists in future.
        Raises ValueError if the query cannot be resolved.
        Raises NotImplementedError for unsupported playlist types.
        """
        input_type = self._detect_input_type(query)

        if input_type == "youtube_video":
            return [self._resolve_youtube_video(query)]
        elif input_type == "youtube_playlist":
            return self._resolve_youtube_playlist(query)
        elif input_type == "spotify_track":
            return [self._resolve_spotify_track(query)]
        elif input_type == "spotify_playlist":
            return self._resolve_spotify_playlist(query)
        else:
            return [self._resolve_search(query)]

    def _detect_input_type(self, query: str) -> str:
        """Detect what type of input the query is."""
        if "youtube.com/playlist" in query:
            return "youtube_playlist"
        if "youtube.com/watch" in query or "youtu.be/" in query:
            return "youtube_video"
        if "music.youtube.com" in query:
            return "youtube_video"  # YT Music URLs work as regular YT
        if "open.spotify.com/track" in query or "spotify:track:" in query:
            return "spotify_track"
        if "open.spotify.com/playlist" in query or "spotify:playlist:" in query:
            return "spotify_playlist"
        return "search"

    def _resolve_search(self, query: str) -> Track:
        """
        Flow 1: Natural language → ytmusicapi → Track with youtube_url

        Uses YouTube Music's search to find the best matching song,
        returning metadata and a playable YouTube video ID.
        """
        result = self.ytmusic.search_track(query)
        if not result:
            raise ValueError(f"No results for: {query}")

        metadata, video_id = result
        return Track(
            title=metadata.title,
            artist=metadata.artist,
            duration_ms=metadata.duration_ms,
            album_art_url=metadata.album_art_url,
            youtube_url=f"https://www.youtube.com/watch?v={video_id}",
            source_url=metadata.source_url,
        )

    def _resolve_youtube_video(self, url: str) -> Track:
        """
        Flow 2: YouTube URL → yt-dlp metadata → Track

        Extracts metadata directly from the YouTube video.
        The URL is already playable.
        """
        metadata = self.youtube.get_video_metadata(url)
        if not metadata:
            raise ValueError(f"Could not load: {url}")

        return Track(
            title=metadata.title,
            artist=metadata.artist,
            duration_ms=metadata.duration_ms,
            album_art_url=metadata.album_art_url,
            youtube_url=url,
            source_url=url,
        )

    def _resolve_spotify_track(self, url: str) -> Track:
        """
        Flow 3: Spotify URL → scraper metadata → ytmusicapi search → Track

        Gets metadata from Spotify (title, artist, duration, album art),
        then searches YouTube Music to find the matching video for playback.
        Uses Spotify metadata for display, YouTube for playback.
        """
        track_info = self.spotify.get_track(url)
        if not track_info:
            raise ValueError(f"Could not load Spotify track: {url}")

        # Extract metadata from Spotify response
        title = track_info.get("name", "")
        artists = track_info.get("artists", [])
        artist = artists[0]["name"] if artists else ""
        duration_ms = track_info.get("duration_ms", 0)

        # Get album art from album images (prefer largest)
        album = track_info.get("album", {})
        images = album.get("images", [])
        # Images are usually sorted by size desc, but let's find largest
        album_art = None
        if images:
            largest = max(images, key=lambda i: i.get("width", 0) * i.get("height", 0))
            album_art = largest.get("url")

        # Search ytmusicapi to get YouTube video
        search_query = f"{title} {artist}"
        result = self.ytmusic.search_track(search_query)
        if not result:
            raise ValueError(f"Could not find on YouTube: {search_query}")

        _, video_id = result

        return Track(
            title=title,
            artist=artist,
            duration_ms=duration_ms,
            album_art_url=album_art,
            youtube_url=f"https://www.youtube.com/watch?v={video_id}",
            source_url=url,
        )

    def _resolve_youtube_playlist(self, url: str) -> list[Track]:
        """Resolve YouTube playlist to list of tracks."""
        return list(self.iter_youtube_playlist(url))

    def _resolve_spotify_playlist(self, url: str) -> list[Track]:
        """Resolve Spotify playlist to list of tracks."""
        return list(self.iter_spotify_playlist(url))

    def iter_spotify_playlist(self, url: str) -> Iterator[Track]:
        """Yield tracks from Spotify playlist one at a time."""
        playlist_tracks = self.spotify.get_playlist_tracks(url)
        if not playlist_tracks:
            raise ValueError(f"Could not load Spotify playlist: {url}")

        for track_info in playlist_tracks[:MAX_PLAYLIST_TRACKS]:
            try:
                yield self._spotify_track_info_to_track(track_info, url)
            except ValueError:
                continue  # Skip tracks that can't be resolved

    def iter_youtube_playlist(self, url: str) -> Iterator[Track]:
        """Yield tracks from YouTube playlist one at a time."""
        entries = self.youtube.get_playlist_entries(url)
        if not entries:
            raise ValueError(f"Could not load YouTube playlist: {url}")

        for entry in entries[:MAX_PLAYLIST_TRACKS]:
            video_id = entry.get("id")
            if not video_id:
                continue
            yield Track(
                title=entry.get("title", "Unknown"),
                artist="YouTube",
                duration_ms=(entry.get("duration") or 0) * 1000,
                album_art_url=None,
                youtube_url=f"https://www.youtube.com/watch?v={video_id}",
                source_url=url,
            )

    def _spotify_track_info_to_track(self, track_info: dict, source_url: str) -> Track:
        """Convert Spotify track dict to Track by searching YTMusic."""
        title = track_info.get("name", "")
        artists = track_info.get("artists", [])
        artist = artists[0]["name"] if artists else ""
        duration_ms = track_info.get("duration_ms", 0)

        result = self.ytmusic.search_track(f"{title} {artist}")
        if not result:
            raise ValueError(f"Could not find: {title}")

        metadata, video_id = result
        return Track(
            title=title,
            artist=artist,
            duration_ms=duration_ms,
            album_art_url=metadata.album_art_url,
            youtube_url=f"https://www.youtube.com/watch?v={video_id}",
            source_url=source_url,
        )
