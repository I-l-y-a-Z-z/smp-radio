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
    channel = bot.get_channel(STAGE_ID)
    
    if channel:
        vc = await channel.connect()
        
        await bot.get_guild(channel.guild.id).me.edit(suppress=False)
        
        while True:
            if not vc.is_playing():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(VIDEO_URL, download=False)
                    url2 = info['url']
                    vc.play(discord.FFmpegPCMAudio(url2, **ffmpeg_options))
            await asyncio.sleep(5)

bot.run(TOKEN)