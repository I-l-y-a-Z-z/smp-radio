import discord
from discord.ext import tasks
import os
import asyncio
from dotenv import load_dotenv

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

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()

# =====================================================================
# THE BOUNCER: Strictly handles Event States, Permissions, and Cleanup
# =====================================================================
@bot.event
async def on_voice_state_update(member, before, after):
    # Only react to the bot's own state changes
    if member.id != bot.user.id:
        return

    # EDGE CASE 1: THE DISCONNECT / KICK (Zombie Process Prevention)
    if before.channel is not None and after.channel is None:
        print("🚨 BOUNCER: Bot was disconnected. Executing nuclear cleanup...")
        vc = member.guild.voice_client
        if vc:
            if vc.is_playing():
                vc.stop() # Assassinate the ghost FFmpeg process
            try:
                # Timeout to prevent asynchronous deadlocks on dead sockets
                await asyncio.wait_for(vc.disconnect(force=True), timeout=2.0)
            except:
                pass
            vc.cleanup() # Wipe Py-cord's internal cache
            
        # Force Discord's backend routing to drop any ghost sessions
        try:
            await member.guild.change_voice_state(channel=None)
        except:
            pass
        return

    # EDGE CASE 2: THE AUDIENCE TRAP
    if after.channel is not None and after.suppress:
        print("🚨 BOUNCER: Bot moved to audience. Requesting Speaker status...")
        try:
            await member.edit(suppress=False)
        except discord.HTTPException as e:
            print(f"⚠️ BOUNCER: Failed to request speaker: {e}")


# =====================================================================
# THE DJ: Strictly handles Connection Routing and Audio Playback
# =====================================================================
@tasks.loop(seconds=5) 
async def heartbeat_loop():
    try:
        # 1. Fetch the Stage Channel
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        if not channel:
            print(f"❌ DJ ERROR: Cannot find Stage channel {STAGE_ID}")
            return
            
        # 2. Stage Instance Check (Create if Discord ended it)
        if channel.instance is None:
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
            except discord.HTTPException as e:
                # Ignore error 150006 (Stage already open, API cache desync)
                if e.code != 150006:
                    pass
                
        # Fetch the official voice client state
        vc = channel.guild.voice_client
        
        # 3. Connection Logic
        if not vc or not vc.is_connected():
            print("🎧 DJ: Bot offline. Initiating UDP connection...")
            try:
                # EDGE CASE 3: The Infinite UDP Handshake Deadlock
                # Wraps the connection in a strict 10-second guillotine timeout
                await asyncio.wait_for(channel.connect(timeout=5.0), timeout=10.0)
            except asyncio.TimeoutError:
                print("⚠️ DJ: Discord Voice Handshake timed out. Breaking deadlock & retrying next loop...")
                return
            except Exception as e:
                print(f"⚠️ DJ: Connection exception: {e}")
                return
                
        # Refresh VC state immediately after a successful connection
        vc = channel.guild.voice_client 
        
        # 4. Audio Playback Logic
        if vc and vc.is_connected():
            my_voice = channel.guild.me.voice
            
            # EDGE CASE 4: The Stage Race Condition
            # ONLY touch the audio file if Discord mathematically confirms we are a speaker
            if my_voice and not my_voice.suppress:
                if not vc.is_playing():
                    if os.path.exists(AUDIO_PATH):
                        print(f"▶️ DJ: Broadcasting infinite stream...")
                        
                        # EDGE CASE 5: Zero-Silence Looping (Native FFmpeg Loop)
                        vc.play(discord.FFmpegPCMAudio(
                            AUDIO_PATH, 
                            before_options='-stream_loop -1', 
                            options='-vn'
                        ))
                    else:
                        print(f"❌ DJ ERROR: Audio file not found at {AUDIO_PATH}")
            else:
                # Failsafe if the Bouncer hasn't secured speaker rights yet
                print("🎧 DJ: Paused. Waiting for Bouncer to secure speaker permissions...")
                try:
                    await channel.guild.me.edit(suppress=False)
                except:
                    pass
                    
    except Exception as e:
        print(f"🔥 System Loop Error: {e}")

# Run the bot
bot.run(TOKEN)