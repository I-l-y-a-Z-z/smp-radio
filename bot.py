import discord
from discord.ext import tasks
import os
import asyncio
from dotenv import load_dotenv
import datetime
import traceback

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
STAGE_ID = int(os.getenv("STAGE_ID"))

intents = discord.Intents.default()
intents.voice_states = True
bot = discord.Bot(intents=intents)

AUDIO_PATH = "/app/audio/non_stop_pop.mp3"
STAGE_TOPIC = "24/7 Non-Stop Pop FM"

# Prevents the heartbeat loop and voice events from racing each other
_connect_lock = asyncio.Lock()


# ─── Helpers ────────────────────────────────────────────────────────────

def log(tag, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


async def cleanup_vc(vc):
    """Fully tear down a VoiceClient — stop audio, disconnect, wipe state."""
    if vc is None:
        return
    try:
        if vc.is_playing():
            vc.stop()
    except Exception:
        pass
    try:
        await asyncio.wait_for(vc.disconnect(force=True), timeout=3.0)
    except Exception:
        pass
    try:
        vc.cleanup()
    except Exception:
        pass


def ffmpeg_alive(vc):
    """Return True only if the underlying FFmpeg process is still running."""
    try:
        src = vc.source
        if src is None:
            return False
        inner = getattr(src, "original", src)
        proc = getattr(inner, "_process", None)
        if proc is None:
            return False
        return proc.poll() is None          # None = still alive
    except Exception:
        return False


def start_playback(vc):
    """Hand the audio file to FFmpeg and start playing on the voice client."""
    def after_playback(error):
        if error:
            log("FFMPEG", f"🔥 Playback crashed: {error}")
        else:
            log("FFMPEG", "Playback ended (file finished or stopped).")

    source = discord.FFmpegOpusAudio(
        AUDIO_PATH,
        before_options="-stream_loop -1",
        options="-vn",
        bitrate=128,
    )
    vc.play(source, after=after_playback)
    log("DJ", "▶️ Playback started.")


# ─── Boot ───────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log("BOOT", f"Logged in as {bot.user}")

    # Load Opus (required for voice)
    if not discord.opus.is_loaded():
        for lib in ("libopus.so.0", "libopus.so", "opus"):
            try:
                discord.opus.load_opus(lib)
                break
            except Exception:
                continue

    if discord.opus.is_loaded():
        log("BOOT", "✅ Opus ready.")
    else:
        log("BOOT", "❌ FATAL: Opus could not be loaded — audio will not work.")

    if not dj_loop.is_running():
        dj_loop.start()


# ─── Voice State Handler ───────────────────────────────────────────────
# Reacts to Discord-side changes: kicks, audience demotion, moves.

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    b_ch = getattr(before.channel, "name", None)
    a_ch = getattr(after.channel, "name", None)
    log("VOICE", f"{b_ch} → {a_ch} | suppress={after.suppress}")

    # ── Disconnected / Kicked ──
    if before.channel is not None and after.channel is None:
        log("VOICE", "Disconnected — cleaning up so DJ loop can reconnect.")
        async with _connect_lock:
            await cleanup_vc(member.guild.voice_client)
        return

    # ── Moved to audience ──
    if after.channel is not None and after.suppress:
        log("VOICE", "Placed in audience — requesting speaker.")
        try:
            await member.edit(suppress=False)
        except discord.HTTPException as e:
            log("VOICE", f"Speaker request failed: {e}")


# ─── DJ Loop ───────────────────────────────────────────────────────────
# Runs every 10 seconds.  Each tick walks through a strict checklist:
#   1. Channel exists?
#   2. Stage instance live?
#   3. Connected to voice?
#   4. Speaker (not audience)?
#   5. Audio actually flowing?

@tasks.loop(seconds=10)
async def dj_loop():
    log("DJ", "─── tick ───")

    try:
        # ── 1. Resolve the Stage Channel ──────────────────────────────
        channel = bot.get_channel(STAGE_ID)
        if channel is None:
            try:
                channel = await bot.fetch_channel(STAGE_ID)
            except discord.NotFound:
                log("DJ", f"❌ Channel {STAGE_ID} does not exist. Sleeping.")
                return
            except discord.Forbidden:
                log("DJ", f"❌ No access to channel {STAGE_ID}.")
                return
            except Exception as e:
                log("DJ", f"❌ Could not fetch channel: {e}")
                return

        if not isinstance(channel, discord.StageChannel):
            log("DJ", f"❌ Channel is a {type(channel).__name__}, not a StageChannel.")
            return

        guild = channel.guild

        # ── 2. Ensure a Stage Instance is live ────────────────────────
        try:
            if channel.instance is None:
                log("DJ", "Stage is not live — creating instance…")
                await channel.create_instance(topic=STAGE_TOPIC)
                log("DJ", "✅ Stage instance created.")
        except discord.HTTPException as e:
            if e.code == 150006:        # "already has an active instance"
                pass
            else:
                log("DJ", f"⚠️ Stage instance issue: {e}")
        except Exception as e:
            log("DJ", f"⚠️ Stage instance check error: {e}")

        # ── 3. Voice Connection ───────────────────────────────────────
        async with _connect_lock:
            vc = guild.voice_client

            # Zombie VC: object exists but socket is dead
            if vc is not None and not vc.is_connected():
                log("DJ", "⚠️ Zombie VC (exists but disconnected). Tearing down…")
                await cleanup_vc(vc)
                vc = None

            # Not connected at all — join
            if vc is None:
                log("DJ", "Connecting…")
                try:
                    vc = await asyncio.wait_for(
                        channel.connect(timeout=10.0),
                        timeout=15.0,
                    )
                    log("DJ", "✅ Connected to voice.")
                    await asyncio.sleep(1.5)        # let Discord settle
                except asyncio.TimeoutError:
                    log("DJ", "⚠️ Handshake timed out. Will retry.")
                    return
                except discord.ClientException as e:
                    # "Already connected" — grab the existing VC
                    log("DJ", f"⚠️ ClientException: {e}")
                    vc = guild.voice_client
                except Exception as e:
                    log("DJ", f"❌ Connection failed: {e}")
                    return

        # Final gate — if still nothing, bail
        if vc is None or not vc.is_connected():
            log("DJ", "Still not connected. Will retry next tick.")
            return

        # ── 4. Speaker Check ──────────────────────────────────────────
        me = guild.me
        if me.voice is None:
            log("DJ", "⚠️ No voice state yet. Will retry.")
            return

        if me.voice.suppress:
            log("DJ", "In audience — requesting speaker…")
            try:
                await me.edit(suppress=False)
                await asyncio.sleep(1.0)
            except discord.HTTPException as e:
                log("DJ", f"Speaker request failed: {e}")
            # Re-check
            if me.voice and me.voice.suppress:
                log("DJ", "Still suppressed. Will retry next tick.")
                return

        # ── 5. Audio Playback ─────────────────────────────────────────
        if vc.is_playing():
            if ffmpeg_alive(vc):
                log("DJ", "✅ Playing & FFmpeg alive.")
                return
            # Zombie audio — flag says playing but FFmpeg is dead
            log("DJ", "⚠️ Zombie audio detected — stopping…")
            try:
                vc.stop()
            except Exception:
                pass
            await asyncio.sleep(0.5)

        # If we're paused for some reason, just resume
        if vc.is_paused():
            log("DJ", "Resuming paused playback…")
            vc.resume()
            return

        # Make sure the file exists before handing it to FFmpeg
        if not os.path.exists(AUDIO_PATH):
            log("DJ", f"❌ Audio file not found: {AUDIO_PATH}")
            return

        log("DJ", "▶️ All checks passed — starting playback…")
        start_playback(vc)

    except Exception as e:
        log("DJ", f"🔥 Unhandled error: {e}")
        traceback.print_exc()


@dj_loop.before_loop
async def wait_for_ready():
    await bot.wait_until_ready()


bot.run(TOKEN)