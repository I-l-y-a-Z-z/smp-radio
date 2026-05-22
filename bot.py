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
# IMPORTANT: This handler ONLY logs. It does NOT call disconnect, cleanup,
# or edit(suppress). Doing so during py-cord's internal state transitions
# corrupts the voice socket and causes silent audio on the next connection.
# The DJ loop handles everything: reconnection, speaker status, playback.

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    b = getattr(before.channel, "name", None)
    a = getattr(after.channel, "name", None)
    log("VOICE", f"{b} → {a} | suppress={after.suppress}")


# ─── DJ Loop ───────────────────────────────────────────────────────────
# Single source of truth. Runs every 10s and walks a strict checklist:
#
#   1. Channel exists & is a StageChannel?
#   2. Stage instance is live?
#   3. Voice client connected?  (clean up zombies, reconnect if needed)
#   4. Bot is a speaker?        (request unsuppress if needed)
#   5. Audio is playing?        (start or restart if zombie)
#
# All recovery actions happen HERE, in sequence, never concurrently.

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
                log("DJ", f"❌ Channel {STAGE_ID} not found.")
                return
            except discord.Forbidden:
                log("DJ", f"❌ No access to {STAGE_ID}.")
                return
            except Exception as e:
                log("DJ", f"❌ Fetch error: {e}")
                return

        if not isinstance(channel, discord.StageChannel):
            log("DJ", f"❌ Not a StageChannel ({type(channel).__name__}).")
            return

        guild = channel.guild

        # ── 2. Stage Instance ─────────────────────────────────────────
        try:
            if channel.instance is None:
                log("DJ", "Creating stage instance…")
                await channel.create_instance(topic=STAGE_TOPIC)
                log("DJ", "✅ Stage created.")
        except discord.HTTPException as e:
            if e.code != 150006:
                log("DJ", f"⚠️ Stage: {e}")
        except Exception as e:
            log("DJ", f"⚠️ Stage check: {e}")

        # ── 3. Voice Connection ───────────────────────────────────────
        vc = guild.voice_client

        # 3a. Zombie: VC object exists but the socket is dead
        if vc is not None and not vc.is_connected():
            log("DJ", "⚠️ Zombie VC detected. Waiting for py-cord cleanup…")
            # Give py-cord time to finish its internal cleanup
            await asyncio.sleep(3)
            # Re-check — py-cord may have cleaned it up by now
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

        # 3b. Not connected — join fresh
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
            # The socket reader, UDP socket, and encryption state all need
            # time to initialize. Starting playback too early = silent audio.
            log("DJ", "Waiting for voice protocol to settle…")
            await asyncio.sleep(4)

            # Re-verify after the wait
            if not vc.is_connected():
                log("DJ", "Lost connection during settle. Retry next tick.")
                return

        # ── 4. Speaker Check & DAVE Sync ──────────────────────────────
        me = guild.me
        if me.voice is None:
            log("DJ", "⚠️ No voice state yet.")
            return

        # DAVE (E2EE) Stage Channel Bug Workaround:
        # If the bot connects and is already a speaker, or if it transitions
        # state without Discord sending the proper DAVE key epochs, it sends
        # packets with the wrong keys (green halo, no audio).
        # Forcing an audience -> speaker transition triggers a fresh key exchange.
        if not getattr(vc, "dave_synced", False):
            log("DJ", "Performing DAVE E2EE key sync...")
            try:
                # Force audience state first
                if not me.voice.suppress:
                    await me.edit(suppress=True)
                    await asyncio.sleep(1.5)
                
                # Now force speaker state to trigger DAVE transition opcodes
                await me.edit(suppress=False)
                await asyncio.sleep(2.5)
                
                # Verify
                me = guild.me
                if me.voice and not me.voice.suppress:
                    log("DJ", "✅ Speaker state verified & DAVE synced.")
                    vc.dave_synced = True
                else:
                    log("DJ", "⚠️ Failed to become speaker. Will retry.")
                    return
            except discord.HTTPException as e:
                log("DJ", f"DAVE sync failed: {e}")
                return
        else:
            # Already synced this connection, just ensure we are still a speaker
            if me.voice.suppress:
                log("DJ", "In audience → requesting speaker…")
                try:
                    await me.edit(suppress=False)
                    await asyncio.sleep(2)
                except discord.HTTPException as e:
                    log("DJ", f"Speaker request failed: {e}")
                    return
                me = guild.me
                if me.voice is None or me.voice.suppress:
                    log("DJ", "Still suppressed. Retry next tick.")
                    return
                log("DJ", "✅ Now a speaker.")

        # ── 5. Audio Playback ─────────────────────────────────────────
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