from dataclasses import dataclass

import yt_dlp

from src.models.track import TrackMetadata


@dataclass
class AudioSource:
    url: str
    http_headers: dict[str, str]


class YouTubeClient:
    YTDL_OPTIONS = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    DURATION_TOLERANCE = 0.10  # 10% tolerance for duration matching

    def __init__(self):
        self._ytdl = yt_dlp.YoutubeDL(self.YTDL_OPTIONS)

    def search_video(self, query: str, target_duration_ms: int = 0) -> str | None:
        """
        Search YouTube for a video matching the query and duration.
        Returns the video URL if a match is found within duration tolerance.
        If target_duration_ms is 0, returns the first result.
        """
        search_query = f"ytsearch5:{query}"
        try:
            result = self._ytdl.extract_info(search_query, download=False)
        except yt_dlp.DownloadError:
            return None

        entries = result.get("entries", [])
        if not entries:
            return None

        # If no duration target, return first result
        if target_duration_ms == 0:
            return entries[0].get("webpage_url") or entries[0].get("url")

        target_seconds = target_duration_ms / 1000
        tolerance = target_seconds * self.DURATION_TOLERANCE

        # Find best match by duration
        best_match = None
        best_diff = float("inf")

        for entry in entries:
            if not entry:
                continue
            duration = entry.get("duration", 0)
            diff = abs(duration - target_seconds)
            if diff <= tolerance and diff < best_diff:
                best_diff = diff
                best_match = entry

        if best_match:
            return best_match.get("webpage_url") or best_match.get("url")

        # If no duration match, return first result as fallback
        return entries[0].get("webpage_url") or entries[0].get("url")

    def get_audio_source(self, video_url: str) -> AudioSource | None:
        """
        Extract the audio source (URL + headers) from a YouTube video.
        Call this right before playback - URLs expire after ~6 hours.
        """
        try:
            info = self._ytdl.extract_info(video_url, download=False)
        except yt_dlp.DownloadError:
            return None

        # Get HTTP headers needed for the request
        http_headers = info.get("http_headers", {})

        # Get the best audio format URL
        formats = info.get("formats", [])
        audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]

        url = None
        if audio_formats:
            # Prefer opus for Discord compatibility
            opus = [f for f in audio_formats if "opus" in f.get("acodec", "").lower()]
            if opus:
                url = opus[0].get("url")
                http_headers = opus[0].get("http_headers", http_headers)
            else:
                url = audio_formats[0].get("url")
                http_headers = audio_formats[0].get("http_headers", http_headers)
        else:
            url = info.get("url")

        if not url:
            return None

        return AudioSource(url=url, http_headers=http_headers)

    def get_video_title(self, video_url: str) -> str | None:
        """Get the title of a YouTube video."""
        try:
            info = self._ytdl.extract_info(video_url, download=False)
            return info.get("title")
        except yt_dlp.DownloadError:
            return None

    def get_video_metadata(self, video_url: str) -> TrackMetadata | None:
        """Get metadata from a YouTube video."""
        try:
            info = self._ytdl.extract_info(video_url, download=False)
            title = info.get("title", "Unknown")
            artist = info.get("uploader", info.get("channel", "Unknown"))
            duration_ms = (info.get("duration") or 0) * 1000
            thumbnail = info.get("thumbnail")

            return TrackMetadata(
                title=title,
                artist=artist,
                duration_ms=duration_ms,
                album_art_url=thumbnail,
                source_url=video_url,
            )
        except yt_dlp.DownloadError:
            return None

    def get_playlist_entries(self, url: str) -> list[dict]:
        """Get video entries from YouTube playlist using flat extraction."""
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        with yt_dlp.YoutubeDL(opts) as ytdl:
            try:
                result = ytdl.extract_info(url, download=False)
            except Exception:
                return []

        entries = result.get("entries", []) if result else []
        return [
            {
                "id": e.get("id"),
                "title": e.get("title", "Unknown"),
                "duration": e.get("duration", 0),
            }
            for e in entries
            if e and e.get("id")
        ]
