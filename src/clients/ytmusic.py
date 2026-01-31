from ytmusicapi import YTMusic

from src.models.track import TrackMetadata


class YTMusicClient:
    """YouTube Music client for searching tracks."""

    def __init__(self):
        self._client = YTMusic()  # No auth needed for search
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def search_track(self, query: str) -> tuple[TrackMetadata, str] | None:
        """
        Search YouTube Music for a track.
        Returns (metadata, video_id) tuple or None if not found.
        """
        try:
            results = self._client.search(query, filter="songs", limit=1)
            if not results:
                return None

            track = results[0]
            video_id = track.get("videoId")
            if not video_id:
                return None

            # Extract artist names
            artists = track.get("artists", [])
            artist_str = ", ".join(a.get("name", "") for a in artists if a.get("name"))

            # Get best thumbnail (last one is usually highest res)
            thumbnails = track.get("thumbnails", [])
            album_art = thumbnails[-1]["url"] if thumbnails else None

            # Duration - ytmusicapi returns duration_seconds
            duration_seconds = track.get("duration_seconds", 0)

            metadata = TrackMetadata(
                title=track.get("title", "Unknown"),
                artist=artist_str or "Unknown",
                duration_ms=duration_seconds * 1000,
                album_art_url=album_art,
                source_url=f"https://music.youtube.com/watch?v={video_id}",
            )

            return metadata, video_id

        except Exception:
            return None
