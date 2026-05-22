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
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()

# --- THE DOMINO EFFECT: Event-Driven State Machine ---
@bot.event
async def on_voice_state_update(member, before, after):
    # Only react to the bot's own state changes
    if member.id != bot.user.id:
        return

    # ANOMALY 2: THE DISCONNECT KICK
    if before.channel is not None and after.channel is None:
        print("🚨 ANOMALY 2 (Kicked): Cleansing socket and initiating re-entry...")
        
        # 1. Clean the ghost state
        vc = member.guild.voice_client
        if vc:
            if vc.is_playing():
                vc.stop()
            try:
                await vc.disconnect(force=True)
            except:
                pass
            vc.cleanup()
            
        # 2. Check Channel & Stage
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        if channel and channel.instance is None:
            try:
                await channel.create_instance(topic=STAGE_TOPIC)
            except discord.HTTPException:
                pass
                
        # 3. Join as Audience (This pushes Domino 1!)
        print("Reconnecting to Stage... (Routing to Anomaly 1)")
        if channel:
            await channel.connect() 
        return

    # ANOMALY 1: THE AUDIENCE TRAP
    # This triggers if you drag the bot manually, OR when Anomaly 2 successfully reconnects!
    if after.channel is not None and after.suppress:
        print("🚨 ANOMALY 1 (Audience Trap): Pushing to Stage and starting audio...")
        
        vc = member.guild.voice_client
        if vc:
            # 1. Kill any ghost audio clinging to the transition
            if vc.is_playing():
                vc.stop()
                
            # 2. Force Speaker Status
            try:
                await member.edit(suppress=False)
                await asyncio.sleep(2) # Give Discord routing 2 seconds to authorize
            except discord.HTTPException as e:
                print(f"Failed to become speaker: {e}")
                return
                
            # 3. Blast the audio
            if os.path.exists(AUDIO_PATH):
                print(f"▶️ Playing track: {AUDIO_PATH}")
                vc.play(discord.FFmpegPCMAudio(
                    AUDIO_PATH, 
                    before_options='-stream_loop -1', 
                    options='-vn'
                ))
            else:
                print(f"ERROR: File not found at {AUDIO_PATH}")

# --- THE HEARTBEAT (Kickstarter) ---
@tasks.loop(seconds=10)
async def heartbeat_loop():
    try:
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        if not channel:
            return
            
        vc = channel.guild.voice_client
        
        # If the bot is completely offline (like on first VPS boot), push the first domino
        if not vc or not vc.is_connected():
            print("Heartbeat: Bot offline. Initiating boot sequence...")
            if channel.instance is None:
                try:
                    await channel.create_instance(topic=STAGE_TOPIC)
                except discord.HTTPException:
                    pass
            await channel.connect() # Triggers Anomaly 1!
            
        # Failsafe: If the stream randomly crashes but the bot is still a speaker
        elif vc and vc.is_connected() and not vc.is_playing():
            if channel.guild.me.voice and not channel.guild.me.voice.suppress:
                if os.path.exists(AUDIO_PATH):
                    print("Heartbeat Failsafe: Restarting dropped audio...")
                    vc.play(discord.FFmpegPCMAudio(
                        AUDIO_PATH, before_options='-stream_loop -1', options='-vn'
                    ))
    except Exception as e:
        print(f"Heartbeat Loop Error: {e}")

bot.run(TOKEN)