import discord
from discord.ext import tasks
import os
import asyncio
import subprocess
from dotenv import load_dotenv
import datetime
import traceback
import logging

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
# Fallback to STAGE_ID if CHANNEL_ID is not set in .env yet
CHANNEL_ID = int(os.getenv("CHANNEL_ID", os.getenv("STAGE_ID")))

intents = discord.Intents.default()
intents.voice_states = True
bot = discord.Bot(intents=intents)

AUDIO_PATH = "/app/audio/non_stop_pop.mp3"

# Verbose voice logging for diagnostics
logging.basicConfig(level=logging.INFO)
logging.getLogger("discord.voice_client").setLevel(logging.DEBUG)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)


def log(tag, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


# ─── Boot ───────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log("BOOT", f"Logged in as {bot.user}")

    if not discord.opus.is_loaded():
        for lib in ("libopus.so.0", "libopus.so", "opus"):
            try:
                discord.opus.load_opus(lib)
                break
            except Exception:
                continue
    log("BOOT", f"Opus loaded: {discord.opus.is_loaded()}")

    try:
        import nacl
        log("BOOT", f"PyNaCl: {nacl.__version__}")
    except ImportError:
        log("BOOT", "❌ FATAL: PyNaCl missing!")

    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        log("BOOT", f"FFmpeg: {r.stdout.split(chr(10))[0]}")
    except Exception as e:
        log("BOOT", f"❌ FFmpeg: {e}")

    if os.path.exists(AUDIO_PATH):
        log("BOOT", f"Audio: {AUDIO_PATH} ({os.path.getsize(AUDIO_PATH) / 1048576:.1f} MB)")
    else:
        log("BOOT", f"❌ Audio missing: {AUDIO_PATH}")

    if not dj_loop.is_running():
        dj_loop.start()


# ─── Voice State Handler ───────────────────────────────────────────────

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    b = getattr(before.channel, "name", None)
    a = getattr(after.channel, "name", None)
    log("VOICE", f"{b} → {a}")


# ─── DJ Loop ───────────────────────────────────────────────────────────
# Single source of truth. Runs every 10s and walks a strict checklist:
#
#   1. Channel exists & is a VoiceChannel?
#   2. Voice client connected?  (clean up zombies, reconnect if needed)
#   3. Audio is playing?        (start or restart if zombie)
#
# All recovery actions happen HERE, in sequence, never concurrently.

@tasks.loop(seconds=10)
async def dj_loop():
    log("DJ", "─── tick ───")

    try:
        # ── 1. Resolve Channel ────────────────────────────────────────
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            try:
                channel = await bot.fetch_channel(CHANNEL_ID)
            except discord.NotFound:
                log("DJ", f"❌ Channel {CHANNEL_ID} not found.")
                return
            except discord.Forbidden:
                log("DJ", f"❌ No access to {CHANNEL_ID}.")
                return
            except Exception as e:
                log("DJ", f"❌ Fetch error: {e}")
                return

        if not isinstance(channel, discord.VoiceChannel) and not isinstance(channel, discord.StageChannel):
            log("DJ", f"❌ Not a VoiceChannel ({type(channel).__name__}).")
            return

        guild = channel.guild

        # ── 2. Voice Connection ───────────────────────────────────────
        vc = guild.voice_client

        # 2a. Zombie: VC object exists but the socket is dead
        if vc is not None and not vc.is_connected():
            log("DJ", "⚠️ Zombie VC detected. Waiting for py-cord cleanup…")
            await asyncio.sleep(3)
            vc = guild.voice_client
            if vc is not None and not vc.is_connected():
                log("DJ", "Zombie still present. Force-cleaning…")
                try:
                    vc.stop()
                except Exception:
                    pass
                try:
                    vc.cleanup()
                except Exception:
                    pass
                vc = None

        # 2b. Not connected — join fresh
        if vc is None:
            log("DJ", "Connecting…")
            try:
                vc = await asyncio.wait_for(
                    channel.connect(timeout=10.0),
                    timeout=15.0,
                )
                log("DJ", "✅ Connected.")
            except asyncio.TimeoutError:
                log("DJ", "⚠️ Timed out.")
                return
            except discord.ClientException as e:
                log("DJ", f"⚠️ {e}")
                vc = guild.voice_client
            except Exception as e:
                log("DJ", f"❌ Connect failed: {e}")
                return

            if vc is None or not vc.is_connected():
                log("DJ", "Connection failed. Retry next tick.")
                return

            # CRITICAL: Let the voice protocol fully settle.
            log("DJ", "Waiting for voice protocol to settle…")
            await asyncio.sleep(4)

            if not vc.is_connected():
                log("DJ", "Lost connection during settle. Retry next tick.")
                return

        # ── 3. Audio Playback ─────────────────────────────────────────
        log("DJ", f"State: connected={vc.is_connected()} playing={vc.is_playing()} "
                   f"endpoint={getattr(vc, 'endpoint', '?')} ssrc={getattr(vc, 'ssrc', '?')}")

        if vc.is_playing():
            # Verify FFmpeg is actually alive
            alive = False
            try:
                src = vc.source
                if src is not None:
                    inner = getattr(src, "original", src)
                    proc = getattr(inner, "_process", None)
                    if proc is not None and proc.poll() is None:
                        alive = True
            except Exception:
                pass

            if alive:
                log("DJ", "✅ Playing & FFmpeg alive.")
                return

            log("DJ", "⚠️ Zombie audio — FFmpeg dead. Stopping…")
            try:
                vc.stop()
            except Exception:
                pass
            await asyncio.sleep(1)

        if vc.is_paused():
            log("DJ", "Resuming paused playback…")
            vc.resume()
            return

        if not os.path.exists(AUDIO_PATH):
            log("DJ", f"❌ File missing: {AUDIO_PATH}")
            return

        # ── Start fresh playback ──────────────────────────────────────
        log("DJ", "▶️ Starting playback…")

        def on_end(error):
            if error:
                log("FFMPEG", f"🔥 Error: {error}")
            else:
                log("FFMPEG", "Stream ended.")

        source = discord.FFmpegPCMAudio(
            AUDIO_PATH,
            before_options="-stream_loop -1",
            options="-vn",
        )
        vc.play(source, after=on_end)
        log("DJ", "▶️ Play command sent.")

    except Exception as e:
        log("DJ", f"🔥 Unhandled: {e}")
        traceback.print_exc()


@dj_loop.before_loop
async def before_loop():
    await bot.wait_until_ready()


bot.run(TOKEN)