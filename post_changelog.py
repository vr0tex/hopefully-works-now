import discord
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1504584461151375461
ROLE_ID = 1500218240637341808

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    channel = client.get_channel(CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="🛠️ Bot Update & Changes",
            description=(
                "**What's New in this Update:**\n\n"
                "**1. Automated Role System**\n"
                "• Added an automatic role assignment system for all new joins.\n"
                "• The `@minor ping` and `@bot changes` roles are now strictly enforced as permanent default auto-roles for all new members.\n\n"
                "**2. Dynamic Mass-Role Command**\n"
                "• Added the `!role add` command to easily mass-assign roles.\n"
                "• You can now choose exactly who receives a new role via 3 buttons: Everyone + Future Members, Future Members Only, or Current Members Only.\n\n"
                "**3. Automated Update Changelog**\n"
                "• Added `!changelog major` and `!changelog minor` commands for staff to easily post these formatted updates to the server."
            ),
            color=discord.Color.brand_green()
        )
        embed.set_footer(text="Paradox Development Team")
        await channel.send(content=f"<@&{ROLE_ID}>", embed=embed)
        print("Message sent successfully!")
    else:
        print("Channel not found!")
    await client.close()

client.run(TOKEN)
