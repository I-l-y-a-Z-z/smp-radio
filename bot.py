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
    print(f"Logged in as {bot.user}")
    if not radio_loop.is_running():
        radio_loop.start()

# --- THE MAGIC FIX: Instant Kick Detection ---
@bot.event
async def on_voice_state_update(member, before, after):
    # Check if the member being updated is the bot itself
    if member.id == bot.user.id:
        # If the bot was in a channel, but is now in None (Kicked/Disconnected)
        if before.channel and after.channel is None:
            print("🚨 KICK DETECTED: Instantly cleaning up ghost voice client...")
            
            # Fetch the official voice client from the guild
            vc = before.channel.guild.voice_client
            if vc:
                if vc.is_playing():
                    vc.stop() # Assassinate ghost FFmpeg
                try:
                    await vc.disconnect(force=True)
                except:
                    pass
                vc.cleanup() # Wipe Py-cord memory
            print("Cleanup complete. Awaiting loop to rebuild connection...")

@tasks.loop(seconds=5)
async def radio_loop():
    try:
        # 1. Fetch channel
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        if not channel:
            return
            
        # 2. Ensure Live Stage exists
        if channel.instance is None:
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
            except discord.HTTPException:
                pass # Ignore if already open
            
        # 3. Connection Check (Using the official guild client)
        vc = channel.guild.voice_client
        
        if not vc or not vc.is_connected():
            print("Connecting to Stage...")
            vc = await channel.connect()
            print("Connected! Becoming speaker...")
            try:
                await channel.guild.me.edit(suppress=False)
                # Give Discord Voice Servers exactly 2 seconds to sync the un-mute
                await asyncio.sleep(2) 
            except:
                pass
        else:
            # Failsafe if dragged to audience
            if channel.guild.me.voice and channel.guild.me.voice.suppress:
                try:
                    await channel.guild.me.edit(suppress=False)
                    await asyncio.sleep(2)
                except:
                    pass
            
        # 4. The Audio Check
        if vc and vc.is_connected() and not vc.is_playing():
            # Only play if we are officially confirmed as a speaker
            if channel.guild.me.voice and not channel.guild.me.voice.suppress:
                if os.path.exists(AUDIO_PATH):
                    print(f"▶️ Starting track: {AUDIO_PATH}")
                    
                    vc.play(discord.FFmpegPCMAudio(
                        AUDIO_PATH, 
                        before_options='-stream_loop -1', 
                        options='-vn'
                    ))
                else:
                    print(f"ERROR: File not found at {AUDIO_PATH}")
                
    except Exception as e:
        print(f"Radio Loop Error: {e}")

# Run the bot
bot.run(TOKEN)