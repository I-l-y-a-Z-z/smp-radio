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

# --- THE UPGRADE: The "Nuclear" Event Listener ---
@bot.event
async def on_voice_state_update(member, before, after):
    if member.id == bot.user.id:
        
        # Trigger cleanup if KICKED (channel becomes None) 
        # OR if moved to AUDIENCE (suppress becomes True)
        is_kicked = (before.channel and after.channel is None)
        is_audience = (after.channel and after.suppress)

        if is_kicked or is_audience:
            print("🚨 STATE ANOMALY: Bot kicked or moved to audience. Initiating nuclear cleanup...")
            
            vc = member.guild.voice_client
            if vc:
                if vc.is_playing():
                    vc.stop() # Assassinate ghost FFmpeg
                try:
                    await vc.disconnect(force=True)
                except:
                    pass
                vc.cleanup() # Wipe Py-cord memory
            print("Cleanup complete. Awaiting loop to rebuild fresh connection...")

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
            
        # (Notice we removed the old Audience check here—the event listener handles it instantly now!)
            
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