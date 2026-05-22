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

# --- THE FIX: Our own memory trap for the voice client ---
active_vc = None 

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not radio_loop.is_running():
        radio_loop.start()

@tasks.loop(seconds=5)
async def radio_loop():
    global active_vc # Tell Python we are using our memory trap
    
    try:
        # 1. Check if channel exists
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        
        if not channel:
            print(f"ERROR: Cannot find Stage channel with ID {STAGE_ID}")
            return
            
        # 2. Check if Stage instance exists (Live Stage)
        if channel.instance is None:
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
                print("Stage created successfully!")
            except discord.HTTPException as e:
                # Error 150006 means the Stage is already open, our cache is just blind.
                if e.code == 150006:
                    pass 
                else:
                    print(f"Warning creating instance: {e}")
            
        # 3. Check if bot is connected to the channel
        vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
        
        if not vc or not vc.is_connected():
            print("Bot is not in the channel. Rebuilding connection...")
            
            # --- THE FIX: Use our trapped VC to kill the zombie ---
            if active_vc:
                print("Executing trapped FFmpeg process and cleaning cache...")
                try:
                    if active_vc.is_playing():
                        active_vc.stop()
                    await active_vc.disconnect(force=True)
                    active_vc.cleanup()
                except Exception as e:
                    print(f"Cleanup warning (safe to ignore): {e}")
                active_vc = None
            
            # Force Discord API to clear any ghost sessions
            try:
                await channel.guild.change_voice_state(channel=None)
                await asyncio.sleep(1)
            except:
                pass
                
            vc = await channel.connect()
            active_vc = vc  # Trap the new connection in our memory!
            
            print("Connected! Requesting to speak...")
            try:
                await channel.guild.me.edit(suppress=False)
                await asyncio.sleep(1) 
            except discord.HTTPException as e:
                print(f"Permission Error trying to speak: {e}")
        else:
            active_vc = vc  # Keep our memory updated if everything is fine
            
            # Failsafe: If the bot is connected but muted/in audience
            if channel.guild.me.voice and channel.guild.me.voice.suppress:
                print("Bot was moved to audience. Reclaiming speaker status...")
                try:
                    await channel.guild.me.edit(suppress=False)
                    await asyncio.sleep(1)
                except discord.HTTPException as e:
                    print(f"Permission Error reclaiming speaker: {e}")
            
        # 4. Check if the audio is actively playing
        if vc and vc.is_connected() and not vc.is_playing():
            # Only try to play if we are actually a speaker (not suppressed)
            if channel.guild.me.voice and not channel.guild.me.voice.suppress:
                if os.path.exists(AUDIO_PATH):
                    print(f"Starting/Restarting track: {AUDIO_PATH}")
                    vc.play(discord.FFmpegPCMAudio(
                        AUDIO_PATH, 
                        before_options='-stream_loop -1', 
                        options='-vn'
                    ))
                else:
                    print(f"ERROR: Audio file not found at {AUDIO_PATH}. Check Coolify volume!")
            else:
                print("Waiting to become a speaker before playing audio...")
                
    except Exception as e:
        print(f"Radio Loop Error: {e}")

# Run the bot
bot.run(TOKEN)