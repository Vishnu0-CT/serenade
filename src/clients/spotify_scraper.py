from spotify_scraper import SpotifyClient


class SpotifyScraperClient:
    """Client for fetching Spotify metadata via web scraping (no API credentials needed)."""

    def __init__(self):
        self._client = SpotifyClient(log_level="ERROR")

    def get_track(self, url: str) -> dict | None:
        """
        Get track metadata from a Spotify URL.

        Returns dict with keys: name, artists (list), duration_ms, album (with images).
        Returns None if track not found.
        """
        try:
            info = self._client.get_track_info(url)
            return info if info else None
        except Exception:
            return None

    def get_playlist_tracks(self, url: str) -> list[dict]:
        """
        Get all tracks from a Spotify playlist URL.

        Returns list of track dicts with keys: name, artists, duration_ms.
        Note: Playlist tracks don't include album art.
        """
        try:
            playlist = self._client.get_playlist_info(url)
            return playlist.get("tracks", []) if playlist else []
        except Exception:
            return []

    def close(self):
        """Close the underlying client."""
        self._client.close()
