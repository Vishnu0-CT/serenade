from dataclasses import dataclass


@dataclass
class TrackMetadata:
    """Metadata for a track. Provider-agnostic intermediate representation."""

    title: str
    artist: str
    duration_ms: int
    album_art_url: str | None
    source_url: str | None


@dataclass
class Track:
    """A track ready to be queued and played."""

    title: str
    artist: str
    duration_ms: int
    album_art_url: str | None
    youtube_url: str  # Ready to play
    source_url: str | None  # Original URL (Spotify/YTMusic link)
    requested_by: str | None = None  # Set when queueing

    @property
    def duration_str(self) -> str:
        """Format duration as MM:SS"""
        total_seconds = self.duration_ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"
