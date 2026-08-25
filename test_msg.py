import discord
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

async def test():
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    
    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")
        channel_id = 1504584461151375461
        role_id = 1500218240637341808
        channel = await client.fetch_channel(channel_id)
        if channel:
            await channel.send(content=f"<@&{role_id}> Test message from script.")
            print("Message sent!")
        else:
            print("Channel not found.")
        await client.close()

    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(test())
