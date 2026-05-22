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
                # Play the file with no video (-vn)
                vc.play(discord.FFmpegPCMAudio(AUDIO_PATH, options='-vn'))
            else:
                print(f"ERROR: Audio file not found at {AUDIO_PATH}. Did the SFTP upload finish?")
                
    except Exception as e:
        print(f"Radio Loop Error: {e}")

bot.run(TOKEN)