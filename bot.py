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
STAGE_ID = int(os.getenv("STAGE_ID"))

intents = discord.Intents.default()
intents.voice_states = True
bot = discord.Bot(intents=intents)

AUDIO_PATH = "/app/audio/non_stop_pop.mp3"
STAGE_TOPIC = "24/7 Non-Stop Pop FM"

_connect_lock = asyncio.Lock()

# Enable verbose Discord voice logging so we can see packet-level issues
logging.basicConfig(level=logging.INFO)
dlog = logging.getLogger("discord.voice_client")
dlog.setLevel(logging.DEBUG)
glog = logging.getLogger("discord.gateway")
glog.setLevel(logging.WARNING)


# ─── Helpers ────────────────────────────────────────────────────────────

def log(tag, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


async def cleanup_vc(vc):
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
    try:
        src = vc.source
        if src is None:
            return False
        inner = getattr(src, "original", src)
        proc = getattr(inner, "_process", None)
        if proc is None:
            return False
        return proc.poll() is None
    except Exception:
        return False


def start_playback(vc):
    def after_playback(error):
        if error:
            log("FFMPEG", f"🔥 Playback crashed: {error}")
        else:
            log("FFMPEG", "Playback ended (file finished or stopped).")

    # Use FFmpegPCMAudio — the most reliable and well-tested path in py-cord.
    # py-cord's VoiceClient.send_audio_packet() handles opus encoding internally.
    # We avoid FFmpegOpusAudio because -stream_loop can break the ogg container framing.
    source = discord.FFmpegPCMAudio(
        AUDIO_PATH,
        before_options="-stream_loop -1",
        options="-vn"
    )
    vc.play(source, after=after_playback)
    log("DJ", "▶️ Playback started (FFmpegPCMAudio).")


# ─── Boot ───────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log("BOOT", f"Logged in as {bot.user}")

    # Opus
    if not discord.opus.is_loaded():
        for lib in ("libopus.so.0", "libopus.so", "opus"):
            try:
                discord.opus.load_opus(lib)
                break
            except Exception:
                continue

    log("BOOT", f"Opus loaded: {discord.opus.is_loaded()}")

    # PyNaCl check — required for voice encryption
    try:
        import nacl
        log("BOOT", f"✅ PyNaCl version: {nacl.__version__}")
    except ImportError:
        log("BOOT", "❌ FATAL: PyNaCl is NOT installed. Voice encryption will fail silently!")

    # FFmpeg check
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5
        )
        first_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        log("BOOT", f"✅ FFmpeg: {first_line}")
    except Exception as e:
        log("BOOT", f"❌ FFmpeg not found: {e}")

    # Audio file check
    if os.path.exists(AUDIO_PATH):
        size_mb = os.path.getsize(AUDIO_PATH) / (1024 * 1024)
        log("BOOT", f"✅ Audio file found: {AUDIO_PATH} ({size_mb:.1f} MB)")

        # Probe the audio file to make sure FFmpeg can read it
        try:
            probe = subprocess.run(
                ["ffmpeg", "-i", AUDIO_PATH, "-f", "null", "-t", "1", "-"],
                capture_output=True, text=True, timeout=10
            )
            if probe.returncode == 0:
                log("BOOT", "✅ Audio file is readable by FFmpeg.")
            else:
                log("BOOT", f"⚠️ FFmpeg probe stderr: {probe.stderr[-500:]}")
        except Exception as e:
            log("BOOT", f"⚠️ Could not probe audio: {e}")
    else:
        log("BOOT", f"❌ Audio file NOT found: {AUDIO_PATH}")

    if not dj_loop.is_running():
        dj_loop.start()


# ─── Voice State Handler ───────────────────────────────────────────────

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    b_ch = getattr(before.channel, "name", None)
    a_ch = getattr(after.channel, "name", None)
    log("VOICE", f"{b_ch} → {a_ch} | suppress={after.suppress}")

    # Disconnected / Kicked
    if before.channel is not None and after.channel is None:
        log("VOICE", "Disconnected — cleaning up.")
        async with _connect_lock:
            await cleanup_vc(member.guild.voice_client)
        return

    # Moved to audience
    if after.channel is not None and after.suppress:
        log("VOICE", "In audience — requesting speaker.")
        try:
            await member.edit(suppress=False)
        except discord.HTTPException as e:
            log("VOICE", f"Speaker request failed: {e}")


# ─── DJ Loop ───────────────────────────────────────────────────────────

@tasks.loop(seconds=10)
async def dj_loop():
    log("DJ", "─── tick ───")

    try:
        # ── 1. Resolve Channel ────────────────────────────────────────
        channel = bot.get_channel(STAGE_ID)
        if channel is None:
            try:
                channel = await bot.fetch_channel(STAGE_ID)
            except discord.NotFound:
                log("DJ", f"❌ Channel {STAGE_ID} does not exist.")
                return
            except discord.Forbidden:
                log("DJ", f"❌ No access to channel {STAGE_ID}.")
                return
            except Exception as e:
                log("DJ", f"❌ Fetch error: {e}")
                return

        if not isinstance(channel, discord.StageChannel):
            log("DJ", f"❌ Not a StageChannel: {type(channel).__name__}")
            return

        guild = channel.guild

        # ── 2. Stage Instance ─────────────────────────────────────────
        try:
            if channel.instance is None:
                log("DJ", "Creating stage instance…")
                await channel.create_instance(topic=STAGE_TOPIC)
                log("DJ", "✅ Stage instance created.")
        except discord.HTTPException as e:
            if e.code != 150006:
                log("DJ", f"⚠️ Stage instance: {e}")
        except Exception as e:
            log("DJ", f"⚠️ Stage check: {e}")

        # ── 3. Voice Connection ───────────────────────────────────────
        async with _connect_lock:
            vc = guild.voice_client

            if vc is not None and not vc.is_connected():
                log("DJ", "⚠️ Zombie VC. Tearing down…")
                await cleanup_vc(vc)
                vc = None

            if vc is None:
                log("DJ", "Connecting…")
                try:
                    vc = await asyncio.wait_for(
                        channel.connect(timeout=10.0),
                        timeout=15.0,
                    )
                    log("DJ", "✅ Connected.")
                    await asyncio.sleep(2)
                except asyncio.TimeoutError:
                    log("DJ", "⚠️ Timed out. Retry next tick.")
                    return
                except discord.ClientException as e:
                    log("DJ", f"⚠️ {e}")
                    vc = guild.voice_client
                except Exception as e:
                    log("DJ", f"❌ Connect failed: {e}")
                    return

        if vc is None or not vc.is_connected():
            log("DJ", "Not connected. Retry next tick.")
            return

        # ── 4. Speaker Check ──────────────────────────────────────────
        me = guild.me
        if me.voice is None:
            log("DJ", "⚠️ No voice state. Retry next tick.")
            return

        if me.voice.suppress:
            log("DJ", "In audience — requesting speaker…")
            try:
                await me.edit(suppress=False)
                await asyncio.sleep(1.5)
            except discord.HTTPException as e:
                log("DJ", f"Speaker failed: {e}")
            if me.voice and me.voice.suppress:
                log("DJ", "Still suppressed. Retry next tick.")
                return

        # Log detailed VC state for diagnosis
        log("DJ", f"VC state: connected={vc.is_connected()} playing={vc.is_playing()} paused={vc.is_paused()}")
        log("DJ", f"VC endpoint: {getattr(vc, 'endpoint', 'N/A')}")
        log("DJ", f"VC SSRC: {getattr(vc, 'ssrc', 'N/A')}")

        # ── 5. Audio ──────────────────────────────────────────────────
        if vc.is_playing():
            if ffmpeg_alive(vc):
                # Peek at the source to verify data flow
                src = vc.source
                inner = getattr(src, "original", src)
                proc = getattr(inner, "_process", None)
                log("DJ", f"✅ Playing. FFmpeg PID={proc.pid if proc else '?'}")
                return
            log("DJ", "⚠️ Zombie audio. Stopping…")
            try:
                vc.stop()
            except Exception:
                pass
            await asyncio.sleep(0.5)

        if vc.is_paused():
            log("DJ", "Resuming…")
            vc.resume()
            return

        if not os.path.exists(AUDIO_PATH):
            log("DJ", f"❌ File missing: {AUDIO_PATH}")
            return

        log("DJ", "▶️ All checks passed — starting playback…")
        start_playback(vc)

    except Exception as e:
        log("DJ", f"🔥 Unhandled: {e}")
        traceback.print_exc()


@dj_loop.before_loop
async def wait_for_ready():
    await bot.wait_until_ready()


bot.run(TOKEN)