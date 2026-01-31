import random
from collections import deque

from src.models.track import Track


class GuildQueue:
    """Queue for a single guild's music playback."""

    def __init__(self):
        self._queue: deque[Track] = deque()
        self.current: Track | None = None
        self.shuffle: bool = False

    def add(self, track: Track) -> int:
        """Add a track to the queue. Returns position in queue (0 = playing next)."""
        self._queue.append(track)
        return len(self._queue) - 1

    def next(self) -> Track | None:
        """Get the next track from the queue. Returns None if empty."""
        if not self._queue:
            self.current = None
            return None

        if self.shuffle:
            self.current = self._pick_shuffle_track()
        else:
            self.current = self._queue.popleft()

        return self.current

    def _pick_shuffle_track(self) -> Track:
        """Pick next track using fair shuffle: alternate requesters when possible."""
        prev_requester = self.current.requested_by if self.current else None

        # Find tracks from other requesters
        other_indices = [
            i for i, t in enumerate(self._queue)
            if t.requested_by != prev_requester
        ]

        if other_indices:
            idx = random.choice(other_indices)
        else:
            # All tracks are from the same requester, pick randomly
            idx = random.randrange(len(self._queue))

        track = self._queue[idx]
        del self._queue[idx]
        return track

    def skip(self) -> Track | None:
        """Skip current track and return the next one."""
        return self.next()

    def clear(self) -> None:
        """Clear all tracks from the queue (keeps current track playing)."""
        self._queue.clear()

    def get_list(self) -> list[Track]:
        """Get a copy of the queue as a list."""
        return list(self._queue)

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return len(self._queue) == 0

    def __len__(self) -> int:
        return len(self._queue)


class QueueManager:
    """Manages queues for all guilds."""

    def __init__(self):
        self._queues: dict[int, GuildQueue] = {}

    def get(self, guild_id: int) -> GuildQueue:
        """Get or create a queue for a guild."""
        if guild_id not in self._queues:
            self._queues[guild_id] = GuildQueue()
        return self._queues[guild_id]

    def remove(self, guild_id: int) -> None:
        """Remove a guild's queue (call when bot leaves voice)."""
        self._queues.pop(guild_id, None)
