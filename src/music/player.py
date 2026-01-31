import asyncio
import queue
import shutil
import subprocess
import threading
from typing import Callable

import discord

from src.clients.youtube import YouTubeClient
from src.models.track import Track
from src.music.queue import GuildQueue


IDLE_TIMEOUT_SECONDS = 120  # 2 minutes

# Audio constants
FRAME_SIZE = 3840  # 20ms of 48kHz stereo 16-bit audio (48000 * 2 * 2 * 0.02)
FRAMES_PER_SECOND = 50

# Buffer configuration
AUDIO_BUFFER_SECONDS = 5.0  # Max buffer size
AUDIO_PREBUFFER_SECONDS = 2.0  # Wait for this much audio before starting playback


class YTDLPAudioSource(discord.AudioSource):
    """Audio source that streams from YouTube via yt-dlp with buffering.

    Uses a background thread to continuously read from ffmpeg into a thread-safe
    buffer, isolating Discord's read() calls from network jitter.
    """

    def __init__(
        self,
        youtube_url: str,
        buffer_seconds: float = AUDIO_BUFFER_SECONDS,
        prebuffer_seconds: float = AUDIO_PREBUFFER_SECONDS,
    ):
        self.youtube_url = youtube_url
        self._process: subprocess.Popen | None = None
        self._ffmpeg: subprocess.Popen | None = None

        # Buffer configuration
        self._buffer_frames = int(buffer_seconds * FRAMES_PER_SECOND)
        self._prebuffer_frames = int(prebuffer_seconds * FRAMES_PER_SECOND)

        # Thread-safe buffer
        self._buffer: queue.Queue[bytes] = queue.Queue(maxsize=self._buffer_frames)
        self._buffer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._prebuffer_ready = threading.Event()
        self._eof = False

        # Start buffering immediately
        self._start_buffering()

    def _start_buffering(self):
        """Start the background buffering thread."""
        self._spawn_processes()
        self._buffer_thread = threading.Thread(target=self._buffer_loop, daemon=True)
        self._buffer_thread.start()

    def _spawn_processes(self):
        """Spawn yt-dlp and ffmpeg processes."""
        ytdlp_path = shutil.which("yt-dlp") or "yt-dlp"
        ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg"

        # yt-dlp outputs audio to stdout, using browser cookies for YouTube auth
        self._process = subprocess.Popen(
            [
                ytdlp_path,
                "-f", "bestaudio/best",
                "-o", "-",
                "--quiet",
                "--cookies-from-browser", "firefox",
                "--remote-components", "ejs:github",
                self.youtube_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        # FFmpeg reads from yt-dlp's stdout and outputs PCM
        self._ffmpeg = subprocess.Popen(
            [
                ffmpeg_path,
                "-thread_queue_size", "4096",
                "-analyzeduration", "2000000",
                "-probesize", "2000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", "pipe:0",
                "-f", "s16le",
                "-ar", "48000",
                "-ac", "2",
                "-loglevel", "quiet",
                "pipe:1",
            ],
            stdin=self._process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _buffer_loop(self):
        """Background thread: continuously read from ffmpeg into buffer."""
        frames_buffered = 0

        while not self._stop_event.is_set():
            data = self._ffmpeg.stdout.read(FRAME_SIZE)

            if len(data) < FRAME_SIZE:
                # End of stream or error
                self._eof = True
                self._prebuffer_ready.set()  # Unblock read() if waiting
                break

            try:
                # Put frame in buffer (blocks if buffer is full, with timeout)
                self._buffer.put(data, timeout=1.0)
                frames_buffered += 1

                # Signal when prebuffer is ready
                if frames_buffered == self._prebuffer_frames:
                    self._prebuffer_ready.set()

            except queue.Full:
                # Buffer full - this means consumer is slower than producer
                # In practice, shouldn't happen with proper buffer sizing
                pass

    def read(self) -> bytes:
        """Read 20ms of audio from buffer."""
        # Wait for prebuffer on first read
        if not self._prebuffer_ready.is_set():
            self._prebuffer_ready.wait(timeout=10.0)

        try:
            return self._buffer.get(timeout=0.5)
        except queue.Empty:
            if self._eof:
                return b""  # Signal end of stream
            # Buffer underrun - return silence rather than speed up
            return b"\x00" * FRAME_SIZE

    def cleanup(self):
        """Clean up processes and threads."""
        self._stop_event.set()

        if self._buffer_thread and self._buffer_thread.is_alive():
            self._buffer_thread.join(timeout=2.0)

        if self._ffmpeg:
            self._ffmpeg.kill()
            self._ffmpeg = None
        if self._process:
            self._process.kill()
            self._process = None


class Player:
    """Handles voice playback for a single guild."""

    def __init__(
        self,
        voice_client: discord.VoiceClient,
        queue: GuildQueue,
        youtube: YouTubeClient,
        on_track_start: Callable[[Track], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ):
        self.voice_client = voice_client
        self.queue = queue
        self.youtube = youtube
        self.on_track_start = on_track_start
        self.on_disconnect = on_disconnect
        self._idle_task: asyncio.Task | None = None

    async def play_next(self) -> Track | None:
        """Play the next track in the queue. Returns the track or None if queue empty."""
        self._cancel_idle_timer()

        track = self.queue.next()
        if not track:
            await self._start_idle_timer()
            return None

        # Use yt-dlp piped audio source
        source = YTDLPAudioSource(track.youtube_url)

        def after_callback(error: Exception | None):
            if error:
                print(f"Player error: {error}")
            # Schedule play_next on the event loop
            asyncio.run_coroutine_threadsafe(
                self.play_next(), self.voice_client.loop
            )

        self.voice_client.play(source, after=after_callback)

        if self.on_track_start:
            self.on_track_start(track)

        return track

    def pause(self) -> bool:
        """Pause playback. Returns True if successful."""
        if self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    def resume(self) -> bool:
        """Resume playback. Returns True if successful."""
        if self.voice_client.is_paused():
            self.voice_client.resume()
            return True
        return False

    def skip(self) -> None:
        """Skip the current track."""
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()  # This triggers the after callback

    async def stop(self) -> None:
        """Stop playback and disconnect."""
        self._cancel_idle_timer()
        self.queue.clear()
        self.queue.current = None
        if self.voice_client.is_connected():
            await self.voice_client.disconnect()
        if self.on_disconnect:
            self.on_disconnect()

    def is_playing(self) -> bool:
        """Check if currently playing or paused."""
        return self.voice_client.is_playing() or self.voice_client.is_paused()

    async def _start_idle_timer(self) -> None:
        """Start the idle disconnect timer."""
        self._idle_task = asyncio.create_task(self._idle_disconnect())

    def _cancel_idle_timer(self) -> None:
        """Cancel the idle disconnect timer if running."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_disconnect(self) -> None:
        """Disconnect after idle timeout."""
        await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        if self.voice_client.is_connected() and not self.is_playing():
            await self.voice_client.disconnect()
            if self.on_disconnect:
                self.on_disconnect()


class PlayerManager:
    """Manages players for all guilds."""

    def __init__(self, youtube: YouTubeClient):
        self._players: dict[int, Player] = {}
        self._youtube = youtube

    def create(
        self,
        guild_id: int,
        voice_client: discord.VoiceClient,
        queue: GuildQueue,
        on_track_start: Callable[[Track], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ) -> Player:
        """Create a new player for a guild."""
        player = Player(
            voice_client=voice_client,
            queue=queue,
            youtube=self._youtube,
            on_track_start=on_track_start,
            on_disconnect=on_disconnect,
        )
        self._players[guild_id] = player
        return player

    def get(self, guild_id: int) -> Player | None:
        """Get an existing player for a guild."""
        return self._players.get(guild_id)

    def remove(self, guild_id: int) -> None:
        """Remove a player for a guild."""
        self._players.pop(guild_id, None)
