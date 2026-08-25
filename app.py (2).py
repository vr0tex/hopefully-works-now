import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
CATEGORY_ID = int(os.getenv('CATEGORY_ID', 0))
STAFF_ROLE_ID = int(os.getenv('STAFF_ROLE_ID', 0))

class ParadoxTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view for 24/7 operation

    @discord.ui.select(
        custom_id="paradox_selector",
        placeholder="Choose your game...",
        options=[
            discord.SelectOption(label="Anime Last Stand", value="ALS", emoji="⚔️"),
            discord.SelectOption(label="Anime Vanguards", value="AV", emoji="🛡️"),
            discord.SelectOption(label="All Star Tower Defense", value="ASTD", emoji="⭐"),
        ]
    )
    async def callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(CATEGORY_ID)
        staff_role = guild.get_role(STAFF_ROLE_ID)

        if not category:
            await interaction.response.send_message(
                "❌ Category not configured. Contact an admin.",
                ephemeral=True
            )
            return

        # Create private channel permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"carry-{select.values[0]}-{user.name}",
            category=category,
            overwrites=overwrites
        )

        await interaction.response.send_message(
            f"✅ Ticket created: {channel.mention}",
            ephemeral=True
        )

        # Welcome embed inside the ticket
        embed = discord.Embed(
            title="⚔️ Paradox Carry System",
            color=discord.Color.purple()
        )
        embed.description = f"Hello {user.mention}, a booster will help you with **{select.values[0]}** shortly."
        await channel.send(embed=embed)


class LockdownChannelSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.channel_select(
        placeholder="Select a channel to lockdown...",
        channel_types=[discord.ChannelType.text]
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        guild = interaction.guild
        
        # Get the access roles list
        access_roles = []
        
        # Get specific roles
        for role_name in ["Admin", "Mods", "Coowner", "vr0tex"]:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                access_roles.append(role)
        
        # Get all roles with "moderator" in the name
        for role in guild.roles:
            if "moderator" in role.name.lower():
                if role not in access_roles:
                    access_roles.append(role)
        
        try:
            # First, lock down for everyone
            await channel.set_permissions(guild.default_role, send_messages=False)
            
            # Block community members specifically
            community_role = discord.utils.get(guild.roles, name="community members")
            if community_role:
                await channel.set_permissions(community_role, send_messages=False)
            
            # Allow send_messages for all access roles
            for role in access_roles:
                await channel.set_permissions(role, send_messages=True)
            
            role_names = ", ".join([role.name for role in access_roles])
            embed = discord.Embed(
                title="🔒 Channel Locked",
                description=f"{channel.mention} has been locked down.\n\n**Access granted to:** {role_names}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to modify channel permissions.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error locking channel: {str(e)}", ephemeral=True)

class ParadoxBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Keeps the dropdown working after restarts
        self.add_view(ParadoxTicketView())
        self.add_view(LockdownChannelSelect())

    async def on_ready(self):
        print(f"✅ Bot logged in as {self.user}")


bot = ParadoxBot()


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """Creates the ticket system embed"""
    if CATEGORY_ID == 0 or STAFF_ROLE_ID == 0:
        await ctx.send(
            "❌ Bot not configured. Set CATEGORY_ID and STAFF_ROLE_ID in .env file."
        )
        return

    embed = discord.Embed(
        title="⚔️ PARADOX | Carry System",
        description="Select a game below to request a professional carry.",
        color=0x2f3136
    )
    await ctx.send(embed=embed, view=ParadoxTicketView())


@bot.command()
@commands.has_permissions(administrator=True)
async def lockdown(ctx, channel: discord.TextChannel = None):
    """Lock a channel - only admins, mods, Coowner, vr0tex, and moderators can type
    
    Usage:
    !lockdown #channel - Lock a specific channel
    !lockdown - Show a channel selector to choose which channel to lock
    """
    if channel:
        # Direct lockdown of specified channel
        guild = ctx.guild
        
        # Get the access roles list
        access_roles = []
        
        # Get specific roles
        for role_name in ["Admin", "Mods", "Coowner", "vr0tex"]:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                access_roles.append(role)
        
        # Get all roles with "moderator" in the name
        for role in guild.roles:
            if "moderator" in role.name.lower():
                if role not in access_roles:
                    access_roles.append(role)
        
        try:
            # First, lock down for everyone
            await channel.set_permissions(guild.default_role, send_messages=False)
            
            # Block community members specifically
            community_role = discord.utils.get(guild.roles, name="community members")
            if community_role:
                await channel.set_permissions(community_role, send_messages=False)
            
            # Allow send_messages for all access roles
            for role in access_roles:
                await channel.set_permissions(role, send_messages=True)
            
            role_names = ", ".join([role.name for role in access_roles])
            embed = discord.Embed(
                title="🔒 Channel Locked",
                description=f"{channel.mention} has been locked down.\n\n**Access granted to:** {role_names}",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to modify channel permissions. Check my role settings.")
        except Exception as e:
            await ctx.send(f"❌ Error locking channel: {str(e)}")
    else:
        # Show channel selector
        embed = discord.Embed(
            title="🔒 Select Channel to Lockdown",
            description="Choose a channel from the dropdown below to lock it down.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, view=LockdownChannelSelect())


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN not found in .env file")
    bot.run(TOKEN)
