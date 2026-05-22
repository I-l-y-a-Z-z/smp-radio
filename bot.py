import discord
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

# This line loads the .env file if it exists
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
STAGE_ID = int(os.getenv("STAGE_ID"))
VIDEO_URL = os.getenv("VIDEO_URL") 

bot = discord.Bot()

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    try:
        # fetch_channel is more reliable than get_channel if the bot cache is empty
        channel = bot.get_channel(STAGE_ID) or await bot.fetch_channel(STAGE_ID)
        
        if not channel:
            print(f"ERROR: Could not find channel with ID {STAGE_ID}. Check your .env file!")
            return
            
        print(f"Found Stage: {channel.name}. Attempting to connect...")
        vc = await channel.connect()
        
        print("Connected to Stage! Attempting to become a speaker...")
        # This requires the Administrator or Mute Members permission
        await channel.guild.me.edit(suppress=False)
        print("Successfully became a speaker! Starting audio stream...")
        
        while True:
            if not vc.is_playing():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(VIDEO_URL, download=False)
                    url2 = info['url']
                    vc.play(discord.FFmpegPCMAudio(url2, **ffmpeg_options))
            await asyncio.sleep(5)
            
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

bot.run(TOKEN)