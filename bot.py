import discord
from discord.ext import tasks
import os
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
    # Start the self-healing loop once the bot boots up
    if not radio_loop.is_running():
        radio_loop.start()

@tasks.loop(seconds=5)
async def radio_loop():
    try:
        # 1. Check if channel exists
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        
        if not channel:
            print(f"ERROR: Cannot find Stage channel with ID {STAGE_ID}")
            return
            
        # 2. Check if Stage instance exists (Live Stage)
        if channel.instance is None:
            print("Stage is not Live. Creating Stage instance...")
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
            except Exception as e:
                print(f"Warning creating instance: {e}")
            
        # 3. Check if bot is connected to the channel
        vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
        
        if not vc or not vc.is_connected():
            # This triggers on boot, if Discord kicks it, or if YOU kick it
            print("Bot is not in the channel. Connecting...")
            vc = await channel.connect()
            print("Connected! Requesting to speak...")
            await channel.guild.me.edit(suppress=False)
        else:
            # Failsafe: If the bot is connected but you manually moved it to the audience
            if channel.guild.me.voice and channel.guild.me.voice.suppress:
                print("Bot was moved to audience. Reclaiming speaker status...")
                await channel.guild.me.edit(suppress=False)
            
        # 4. Check if the audio is actively playing
        if vc and vc.is_connected() and not vc.is_playing():
            if os.path.exists(AUDIO_PATH):
                print(f"Starting/Restarting track from the beginning: {AUDIO_PATH}")
                # Play the file natively using FFmpeg's infinite stream loop flag
                vc.play(discord.FFmpegPCMAudio(
                    AUDIO_PATH, 
                    before_options='-stream_loop -1', 
                    options='-vn'
                ))
            else:
                print(f"ERROR: Audio file not found at {AUDIO_PATH}. Check Coolify volume!")
                
    except Exception as e:
        print(f"Radio Loop Error: {e}")

# Run the bot
bot.run(TOKEN)