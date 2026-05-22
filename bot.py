import discord
from discord.ext import tasks
import os
import asyncio
from dotenv import load_dotenv
import datetime

# Load environment variables
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
STAGE_ID = int(os.getenv("STAGE_ID"))

# Initialize bot with required voice intents
intents = discord.Intents.default()
intents.voice_states = True
bot = discord.Bot(intents=intents)

# Configuration constants
AUDIO_PATH = "/app/audio/non_stop_pop.mp3"
STAGE_TOPIC = "24/7 Non-Stop Pop FM"

# Diagnostic Logger
def log(module, message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{module}] {message}")

@bot.event
async def on_ready():
    log("SYSTEM", f"✅ Logged in successfully as {bot.user}")
    if not heartbeat_loop.is_running():
        log("SYSTEM", "Starting DJ Heartbeat Loop...")
        heartbeat_loop.start()

# =====================================================================
# THE BOUNCER: Strictly handles Event States, Permissions, and Cleanup
# =====================================================================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    log("BOUNCER", f"State Update Triggered -> Channel: {getattr(before.channel, 'name', 'None')} to {getattr(after.channel, 'name', 'None')} | Suppress: {after.suppress}")

    # EDGE CASE 1: THE DISCONNECT / KICK 
    if before.channel is not None and after.channel is None:
        log("BOUNCER-KICK", "Bot was disconnected. Deploying background socket execution...")
        vc = member.guild.voice_client
        if vc:
            if vc.is_playing():
                vc.stop() 
            
            # THE FIX: Run the official disconnect as a background task. 
            # This forces Py-cord to delete the ghost object without freezing the Bouncer!
            async def execute_ghost(zombie_vc):
                try:
                    await asyncio.wait_for(zombie_vc.disconnect(force=True), timeout=2.0)
                except:
                    log("BOUNCER-KICK", "Disconnect timed out, forcing cache wipe...")
                finally:
                    zombie_vc.cleanup()
                    log("BOUNCER-KICK", "Ghost socket fully purged from Py-cord memory.")

            bot.loop.create_task(execute_ghost(vc))
        return

    # EDGE CASE 2: THE AUDIENCE TRAP
    if after.channel is not None and after.suppress:
        log("BOUNCER-AUDIENCE", "Bot detected in audience. Requesting Speaker status...")
        try:
            await member.edit(suppress=False)
            log("BOUNCER-AUDIENCE", "Speaker request sent successfully.")
        except discord.HTTPException as e:
            log("BOUNCER-AUDIENCE", f"❌ Failed to request speaker permissions: {e}")


# =====================================================================
# THE DJ: Strictly handles Connection Routing and Audio Playback
# =====================================================================
@tasks.loop(seconds=5) 
async def heartbeat_loop():
    log("DJ-TICK", "--- Loop Triggered ---")
    try:
        # 1. Fetch the Stage Channel
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        if not channel:
            log("DJ-ERROR", f"❌ Cannot find Stage channel ID {STAGE_ID}")
            return
            
        # 2. Stage Instance Check 
        if channel.instance is None:
            log("DJ-STAGE", "Stage is dead. Attempting to create Live instance...")
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
                log("DJ-STAGE", "Live Stage instance created!")
            except discord.HTTPException as e:
                if e.code != 150006:
                    log("DJ-STAGE", f"Warning creating instance: {e}")
                
        # Fetch the official voice client state
        vc = channel.guild.voice_client
        log("DJ-STATE", f"VC Exists: {vc is not None} | VC Connected: {vc.is_connected() if vc else False}")
        
        # 3. Connection Logic
        if not vc or not vc.is_connected():
            log("DJ-CONNECT", "Bot is disconnected. Initiating UDP Handshake...")
            
            # THE FIX: If Py-cord tries to hand the DJ a dead, recycled socket, destroy it.
            if vc:
                log("DJ-CONNECT", "⚠️ Zombie VoiceClient detected! Ripping it out before reconnecting...")
                try:
                    await asyncio.wait_for(vc.disconnect(force=True), timeout=1.0)
                except:
                    pass
                vc.cleanup()
            
            try:
                await asyncio.wait_for(channel.connect(timeout=5.0), timeout=10.0)
                log("DJ-CONNECT", "✅ UDP Handshake complete! Connected to voice servers.")
            except asyncio.TimeoutError:
                log("DJ-CONNECT", "⚠️ Discord Voice Handshake timed out. Waiting for next loop...")
                return
            except Exception as e:
                log("DJ-CONNECT", f"❌ Connection exception: {e}")
                return
                
        # Refresh VC state 
        vc = channel.guild.voice_client 
        
        # 4. Audio Playback Logic
        if vc and vc.is_connected():
            my_voice = channel.guild.me.voice
            log("DJ-AUDIO-CHECK", f"My Voice State Exists: {my_voice is not None} | Suppressed: {my_voice.suppress if my_voice else 'N/A'}")
            
            if my_voice and not my_voice.suppress:
                log("DJ-AUDIO-CHECK", f"Is Playing Currently: {vc.is_playing()}")
                
                if not vc.is_playing():
                    log("DJ-AUDIO-CHECK", f"Checking file path: {AUDIO_PATH}")
                    if os.path.exists(AUDIO_PATH):
                        log("DJ-PLAY", "▶️ ALL CHECKS PASSED. Handing file to FFmpeg...")
                        
                        def ffmpeg_spy(error):
                            if error:
                                log("FFMPEG-SPY", f"🔥 CRITICAL: FFmpeg process crashed! Error: {error}")
                            else:
                                log("FFMPEG-SPY", "Stream ended gracefully (File finished or was manually stopped).")

                        vc.play(discord.FFmpegPCMAudio(
                            AUDIO_PATH, 
                            before_options='-stream_loop -1', 
                            options='-vn'
                        ), after=ffmpeg_spy)
                        
                        log("DJ-PLAY", "FFmpeg play command executed.")
                    else:
                        log("DJ-ERROR", f"❌ File missing at {AUDIO_PATH}.")
            else:
                log("DJ-PAUSE", "Waiting for Bouncer to secure speaker permissions...")
                try:
                    await channel.guild.me.edit(suppress=False)
                except:
                    pass
                    
    except Exception as e:
        log("SYSTEM-ERROR", f"🔥 Unhandled Heartbeat Loop Error: {e}")

bot.run(TOKEN)