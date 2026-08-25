import discord
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class V2Embed(discord.Embed):
    def __init__(self, **kwargs):
        kwargs.setdefault('color', discord.Color.blue())
        super().__init__(**kwargs)

async def send_updates():
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    
    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")
        channel_id = 1504584461151375461
        channel = await client.fetch_channel(channel_id)
        if channel:
            embed = V2Embed(
                title="🛠️ Bot Update & Changes",
                description=(
                    "**What's New in this Update:**\n\n"
                    "**1. Universal Tower Defense (UTD) Support**\n\n"
                    "• Added UTD to carry requests and helper applications.\n"
                    "• Added custom application questions for UTD helpers.\n\n"
                    "Paradox Development Team"
                ),
                color=discord.Color.brand_green()
            )
            await channel.send(embed=embed)
            print("Updates message sent successfully!")
        else:
            print("Channel not found.")
        await client.close()

    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(send_updates())
