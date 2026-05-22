import discord
from discord.ext import tasks
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
STAGE_ID = int(os.getenv("STAGE_ID"))

# Initialize bot with required intents
intents = discord.Intents.default()
intents.voice_states = True
bot = discord.Bot(intents=intents)

# This points to the volume we mapped in Coolify
AUDIO_PATH = "/app/audio/non_stop_pop.mp3"

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not radio_loop.is_running():
        radio_loop.start()

@tasks.loop(seconds=5)
async def radio_loop():
    try:
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        
        if not channel:
            print(f"ERROR: Cannot find Stage channel {STAGE_ID}")
            return
            
        # --- THE FIX: Auto-Restart the Stage Instance ---
        if channel.instance is None:
            print("Stage is not Live. Starting a new Stage instance...")
            # You can change this topic string to whatever you want the Stage title to be!
            await channel.create_instance(topic="24/7 Non-Stop Pop FM")
            
        vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
        
        # Connect and become speaker if not already in the channel
        if not vc or not vc.is_connected():
            print("Connecting to Stage...")
            vc = await channel.connect()
            print("Connected! Requesting to speak...")
            await channel.guild.me.edit(suppress=False)
            
        # If the music stops (or hasn't started), play the local MP3
        if vc and not vc.is_playing():
            if os.path.exists(AUDIO_PATH):
                print(f"Playing audio: {AUDIO_PATH}")
                # Playing with the infinite loop flag
                vc.play(discord.FFmpegPCMAudio(AUDIO_PATH, before_options='-stream_loop -1', options='-vn'))
            else:
                print(f"ERROR: Audio file not found at {AUDIO_PATH}")
                
    except Exception as e:
        print(f"Radio Loop Error: {e}")

bot.run(TOKEN)