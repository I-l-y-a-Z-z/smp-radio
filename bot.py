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
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()

# --- THE BOUNCER: Strictly handles permissions and cleanup ---
@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    # ANOMALY 2: THE DISCONNECT KICK
    if before.channel is not None and after.channel is None:
        print("🚨 BOUNCER (Kicked): Cleansing socket...")
        vc = member.guild.voice_client
        if vc:
            if vc.is_playing():
                vc.stop()
            try:
                await vc.disconnect(force=True)
            except:
                pass
            vc.cleanup()
        return

    # ANOMALY 1: THE AUDIENCE TRAP
    if after.channel is not None and after.suppress:
        print("🚨 BOUNCER (Audience Trap): Requesting Speaker Status...")
        try:
            await member.edit(suppress=False)
        except discord.HTTPException as e:
            print(f"Failed to become speaker: {e}")

# --- THE DJ: Strictly handles connection and audio ---
@tasks.loop(seconds=5) 
async def heartbeat_loop():
    try:
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        if not channel:
            return
            
        if channel.instance is None:
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
            except discord.HTTPException:
                pass
                
        vc = channel.guild.voice_client
        
        # 1. Connect if offline
        if not vc or not vc.is_connected():
            print("🎧 DJ: Bot offline. Initiating connection...")
            await channel.connect() 
            
        # 2. Play if connected AND speaker
        elif vc.is_connected():
            # Verify we are officially a speaker before touching audio
            if channel.guild.me.voice and not channel.guild.me.voice.suppress:
                if not vc.is_playing():
                    if os.path.exists(AUDIO_PATH):
                        print(f"▶️ DJ: Starting track...")
                        vc.play(discord.FFmpegPCMAudio(
                            AUDIO_PATH, 
                            before_options='-stream_loop -1', 
                            options='-vn'
                        ))
                    else:
                        print(f"ERROR: File not found at {AUDIO_PATH}")
            else:
                print("🎧 DJ: Waiting for Bouncer to secure speaker permissions...")
                
    except Exception as e:
        print(f"Heartbeat Loop Error: {e}")

bot.run(TOKEN)