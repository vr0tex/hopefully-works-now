# Paradox Discord Bot

A Discord bot for managing carry request tickets using a dropdown menu system.

## Features

- ✅ Ticket system with dropdown menu
- ✅ Vouch system for boosters
- ✅ Helper Application system
- ✅ Game selection (10+ popular anime games)
- ✅ Private ticket channels with proper permissions
- ✅ Staff role access to tickets
- ✅ Persistent views (survives bot restarts)

## Setup

### Prerequisites

- Python 3.8+
- Discord.py 2.3+

### Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** from the example:
   ```bash
   cp .env.example .env
   ```

3. **Configure your `.env` file:**
   - `DISCORD_TOKEN`: Your bot token from [Discord Developer Portal](https://discord.com/developers/applications)
   - `CATEGORY_ID`: The category ID where tickets will be created
   - `STAFF_ROLE_ID`: The role ID for staff who can access tickets

### Getting IDs

To find your IDs:
1. Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
2. Right-click on the category/role and select "Copy ID"

## Running the Bot

```bash
python app.py.py
```

### Deploying on Railway

Railway uses the included `Procfile` to start the bot as a worker. Add these variables in the Railway service settings:

- `DISCORD_TOKEN`
- `CATEGORY_ID`
- `STAFF_ROLE_ID`
- `VOUCH_CHANNEL_ID`
- `HELPER_CHANNEL_ID`
- `SUPABASE_URL` and `SUPABASE_KEY` (optional)

## Commands

- `!setup` - Creates the carry ticket system embed (admin only)
- `!helper_setup` - Creates the helper application embed (admin only)
- `!vouches [user]` - Check vouches for a booster (default: yourself)

## How It Works

1. Users click the dropdown menu and select a game
2. A private ticket channel is created in the designated category
3. Only the user and staff role can see the channel
4. Staff can assist with the carry request

## File Structure

```
.
├── app.py.py           # Main bot code (use this)
├── app.py (2).py       # Legacy bot code (backup)
├── requirements.txt    # Python dependencies
├── .env.example        # Example environment variables
├── .gitignore          # Git ignore rules
└── README.md           # This file
```
