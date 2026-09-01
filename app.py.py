import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
import asyncio
import sqlite3
from utils import V2Embed, create_vouch_card, create_profile_card, EmbedFactory
from supabase import create_client, Client
import json
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
WELCOME_CHANNEL_ID = 1500185807544254734
WELCOME_SETTINGS_FILE = os.path.join(BASE_DIR, "welcome_settings.json")
WELCOME_ENABLED = {}
WELCOME_CHANNELS = {}
VOUCH_DB_PATH = os.path.join(BASE_DIR, "vouches.db")

# Persistent local voucher storage. This avoids resets when the bot restarts or when Supabase is unavailable.

def init_vouch_database():
    conn = sqlite3.connect(VOUCH_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bonus_vouches (
            user_id TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0,
            games_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vouch_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booster_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            game TEXT NOT NULL,
            feedback TEXT,
            star_rating INTEGER NOT NULL DEFAULT 5,
            ticket_id TEXT,
            booster_name TEXT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'local'
        )
        """
    )
    conn.commit()
    conn.close()

    legacy_file = os.path.join(BASE_DIR, "bonus_vouches.json")
    if os.path.exists(legacy_file):
        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            if isinstance(legacy_data, dict):
                for user_id, user_data in legacy_data.items():
                    if not isinstance(user_data, dict):
                        continue
                    legacy_total = max(0, int(user_data.get("total", 0)))
                    legacy_games = user_data.get("games") or {}
                    if legacy_total > 0:
                        conn = sqlite3.connect(VOUCH_DB_PATH)
                        conn.execute(
                            """
                            INSERT INTO bonus_vouches (user_id, total, games_json)
                            VALUES (?, ?, ?)
                            ON CONFLICT(user_id)
                            DO UPDATE SET total = excluded.total, games_json = excluded.games_json
                            """,
                            (str(user_id), legacy_total, json.dumps(legacy_games)),
                        )
                        conn.commit()
                        conn.close()
                print(f"✅ Migrated legacy bonus vouches from {legacy_file} into SQLite")
        except Exception as exc:
            print(f"⚠️ Could not migrate legacy bonus vouches: {exc}")

    return VOUCH_DB_PATH


def get_welcome_channel_id_for_guild(guild_id):
    try:
        guild_id = int(guild_id)
    except (TypeError, ValueError):
        return WELCOME_CHANNEL_ID
    return int(WELCOME_CHANNELS.get(guild_id, WELCOME_CHANNEL_ID))


def load_welcome_settings():
    global WELCOME_CHANNELS
    try:
        if not os.path.exists(WELCOME_SETTINGS_FILE):
            return {}
        with open(WELCOME_SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}

        enabled = {}
        channel_map = {}
        for guild_id, value in data.items():
            try:
                guild_key = int(guild_id)
            except (TypeError, ValueError):
                continue

            if isinstance(value, dict):
                enabled[guild_key] = bool(value.get("enabled", False))
                channel_id = value.get("channel_id")
                if channel_id is not None:
                    try:
                        channel_map[guild_key] = int(channel_id)
                    except (TypeError, ValueError):
                        pass
            else:
                enabled[guild_key] = bool(value)

        WELCOME_ENABLED.clear()
        WELCOME_ENABLED.update(enabled)
        WELCOME_CHANNELS.clear()
        WELCOME_CHANNELS.update(channel_map)
        return WELCOME_ENABLED
    except Exception as exc:
        print(f"DEBUG: Failed to load welcome settings: {exc}")
        return WELCOME_ENABLED


def save_welcome_settings():
    try:
        payload = {}
        for guild_id, enabled in WELCOME_ENABLED.items():
            guild_key = int(guild_id)
            payload[str(guild_key)] = {
                "enabled": bool(enabled),
                "channel_id": int(WELCOME_CHANNELS.get(guild_key, WELCOME_CHANNEL_ID)),
            }
        with open(WELCOME_SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception as exc:
        print(f"DEBUG: Failed to save welcome settings: {exc}")


def get_asset_path(filename):
    asset_path = os.path.join(ASSETS_DIR, filename)
    if os.path.isfile(asset_path):
        return asset_path
    root_path = os.path.join(BASE_DIR, filename)
    return root_path if os.path.isfile(root_path) else None

async def set_bot_avatar_from_asset(bot):
    """Use the repo's Paradox asset as the current bot avatar when available."""
    avatar_candidates = [
        "paradox img.png",
        "bot_avatar.png",
        "bot_avatar.jpg",
        "bot_avatar.jpeg",
        "bot_profile.png",
        "profile.png",
        "setup_header.png",
        "paradox.png",
        "paradox.jpg",
        "yuji.png",
    ]

    for filename in avatar_candidates:
        avatar_path = get_asset_path(filename)
        if not avatar_path or not os.path.isfile(avatar_path):
            continue
        try:
            with open(avatar_path, "rb") as asset_file:
                avatar_bytes = asset_file.read()
            await bot.user.edit(avatar=avatar_bytes)
            print(f"✅ Bot avatar updated from asset: {avatar_path}")
            return True
        except Exception as exc:
            print(f"⚠️ Failed to set bot avatar from {avatar_path}: {exc}")
    print("⚠️ No Paradox avatar asset found in project files.")
    return False

GAME_ROLE_MAP = {
    "ALS": 1500199051952656578,
    "AV": 1500198955940712468,
    "UTD": 1505300013604147332,
    "AE": 1541834030717075457,
}

# CPU Optimization: Limit bot to 25% CPU usage (1 core out of 4)
try:
    import psutil
    process = psutil.Process(os.getpid())
    cpu_count = psutil.cpu_count(logical=True)
    # Assign to core 0 only (25% on 4-core, 20% on 5-core, etc)
    cores_to_use = max(1, cpu_count // 4)
    process.cpu_affinity(list(range(cores_to_use)))
    # Lower process priority to use less CPU
    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if hasattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS') else 10)
    print(f"✅ CPU Optimization: {cores_to_use} core(s), reduced priority")
except Exception as e:
    print(f"⚠️ CPU optimization partial: {e}")

# Global CPU throttling
_cpu_throttle_enabled = True
_message_batch_time = 0.05  # Batch messages every 50ms
_keyword_check_cooldown = 2  # Check keywords max once every 2 seconds per user
_keyword_cooldowns = {}  # user_id -> last_check_time

def get_bonus_vouches(user_id):
    try:
        conn = sqlite3.connect(VOUCH_DB_PATH)
        row = conn.execute(
            "SELECT total, games_json FROM bonus_vouches WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        conn.close()
        if row is None:
            return {"total": 0, "games": {}}
        games = json.loads(row[1] or "{}") if row[1] else {}
        return {"total": int(row[0]), "games": games}
    except Exception as exc:
        print(f"Warning: failed to read bonus vouches from SQLite: {exc}")
        try:
            with open(os.path.join(BASE_DIR, "bonus_vouches.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(str(user_id), {"total": 0, "games": {}})
        except (FileNotFoundError, json.JSONDecodeError):
            return {"total": 0, "games": {}}


def save_vouch_record(booster_id, customer_id, game, feedback, star_rating=5, ticket_id=None, booster_name=None, source='local'):
    try:
        conn = sqlite3.connect(VOUCH_DB_PATH)
        cursor = conn.execute(
            """
            INSERT INTO vouch_records (
                booster_id, customer_id, game, feedback, star_rating, ticket_id, booster_name, created_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(booster_id),
                str(customer_id),
                game,
                feedback,
                int(star_rating),
                str(ticket_id) if ticket_id is not None else None,
                booster_name,
                datetime.now(timezone.utc).isoformat(),
                source,
            ),
        )
        conn.commit()
        record_id = cursor.lastrowid
        conn.close()
        return record_id
    except Exception as exc:
        print(f"Error saving local vouch record: {exc}")
        return None


def get_vouch_rank(total_vouches):
    ranks = [
        (500, "Legendary"),
        (250, "Elite"),
        (100, "Diamond"),
        (50, "Platinum"),
        (25, "Gold"),
        (10, "Bronze"),
    ]
    for threshold, rank in ranks:
        if total_vouches >= threshold:
            return rank
    return "Unranked"

def get_total_vouches(user_id, minimum_total=0):
    total_vouches = get_bonus_vouches(user_id)["total"]

    try:
        conn = sqlite3.connect(VOUCH_DB_PATH)
        local_total = conn.execute(
            "SELECT COUNT(*) FROM vouch_records WHERE booster_id = ?",
            (str(user_id),),
        ).fetchone()[0]
        conn.close()
    except Exception as exc:
        print(f"Error querying local vouches: {exc}")
        local_total = 0

    database_total = 0
    if supabase:
        try:
            result = supabase.table("vouches").select("id", count="exact").eq(
                "booster_id", str(user_id)
            ).execute()
            returned_rows = len(result.data or [])
            database_total = max(result.count or 0, returned_rows)
        except Exception as exc:
            print(f"Error querying Supabase vouches: {exc}")

    total = total_vouches + local_total + database_total
    if total < minimum_total:
        return minimum_total
    return total

def create_vouch_embed(customer, booster, game, feedback, total_vouches, ticket_id, star_rating=5, include_details=True):
    embed = discord.Embed(title="🟢 VOUCH RECEIVED", color=0xF4D03F)
    embed.set_thumbnail(url=booster.display_avatar.url)
    embed.add_field(name="👤 From", value=customer.mention, inline=False)
    embed.add_field(name="🛡️ Helper", value=booster.mention, inline=False)
    if include_details:
        stars_display = "⭐" * star_rating + "☆" * (5 - star_rating)
        embed.add_field(name="⭐ Rating", value=f"{stars_display} ({star_rating}/5)", inline=False)
        embed.add_field(name="📋 Comment", value=feedback[:1024], inline=False)
        embed.add_field(name="🎮 Game", value=game, inline=False)
        embed.add_field(name="🎟️ Ticket", value=f"#{ticket_id}", inline=False)
    else:
        embed.add_field(name="🎮 Main Game", value=game, inline=False)
    embed.add_field(name="🏅 Rank", value=get_vouch_rank(total_vouches), inline=False)
    embed.add_field(name="🏆 Total Vouches", value=str(total_vouches), inline=False)
    embed.add_field(
        name="🕘 Registered",
        value=discord.utils.format_dt(datetime.now(timezone.utc), style="F"),
        inline=False,
    )
    return embed

def add_bonus_vouches(user_id, amount, game):
    user_data = get_bonus_vouches(user_id)
    user_data["total"] = int(user_data.get("total", 0)) + int(amount)
    games = user_data.get("games", {}) if isinstance(user_data.get("games", {}), dict) else {}
    games[game] = games.get(game, 0) + int(amount)
    user_data["games"] = games

    try:
        conn = sqlite3.connect(VOUCH_DB_PATH)
        conn.execute(
            """
            INSERT INTO bonus_vouches (user_id, total, games_json)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET total = excluded.total, games_json = excluded.games_json
            """,
            (str(user_id), user_data["total"], json.dumps(games)),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"Error updating bonus vouches in SQLite: {exc}")
        data = {}
        try:
            with open(os.path.join(BASE_DIR, "bonus_vouches.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        data[str(user_id)] = user_data
        with open(os.path.join(BASE_DIR, "bonus_vouches.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    return user_data["total"]

AUTO_ROLES_FILE = "auto_roles.json"

def get_auto_roles():
    base_roles = [1504585688761241681, 1500218240637341808]
    if os.path.exists(AUTO_ROLES_FILE):
        try:
            with open(AUTO_ROLES_FILE, "r") as f:
                data = json.load(f)
                saved_roles = data.get("roles", [])
                for r in saved_roles:
                    if r not in base_roles:
                        base_roles.append(r)
        except Exception:
            pass
    return base_roles

def add_auto_role(role_id):
    roles = get_auto_roles()
    if role_id not in roles:
        roles.append(role_id)
        with open(AUTO_ROLES_FILE, "w") as f:
            json.dump({"roles": roles}, f)
        return True
    return False

USER_MESSAGES_FILE = "user_messages.json"

# In-memory cache for message tracking (reduces disk I/O)
_message_cache = {}  # user_id -> list of timestamps
_last_save = datetime.now(timezone.utc).timestamp()
_save_interval = 900  # Save to disk every 15 minutes (reduced frequency for web hosting)

# CPU throttling: Add small delay between message events to prevent CPU spikes
_message_limiter = asyncio.Semaphore(5)  # Max 5 concurrent message handlers
_last_message_time = 0
_min_message_interval = 0.01  # 10ms minimum between processing messages

# Thread pool executor for CPU-intensive operations (prevents blocking event loop)
import concurrent.futures
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)  # Single threaded to limit CPU

def load_user_messages():
    """Load from disk into cache"""
    if os.path.exists(USER_MESSAGES_FILE):
        try:
            with open(USER_MESSAGES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_user_messages(data):
    """Save cache to disk"""
    try:
        with open(USER_MESSAGES_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving user messages: {e}")

async def periodic_save_messages():
    """Background task to save message cache to disk every 5 minutes"""
    while True:
        try:
            await asyncio.sleep(_save_interval)
            if _message_cache:
                # Prune old entries and save
                now = datetime.now(timezone.utc).timestamp()
                cutoff = now - 86400
                
                pruned_cache = {}
                for user_id, timestamps in _message_cache.items():
                    valid = [t for t in timestamps if t >= cutoff]
                    if valid:
                        pruned_cache[user_id] = valid
                
                save_user_messages(pruned_cache)
        except Exception as e:
            print(f"Error in periodic_save_messages: {e}")

def track_message(user_id):
    """Track message in memory (very fast, minimal CPU)"""
    global _message_cache
    user_key = str(user_id)
    now = datetime.now(timezone.utc).timestamp()
    
    if user_key not in _message_cache:
        _message_cache[user_key] = []
    
    _message_cache[user_key].append(now)
    
    # Keep only last 100 messages per user in memory to limit memory usage
    if len(_message_cache[user_key]) > 100:
        cutoff = now - 86400
        _message_cache[user_key] = [t for t in _message_cache[user_key] if t >= cutoff][-100:]

def get_message_count_last_24h(user_id):
    """Get message count from in-memory cache"""
    user_key = str(user_id)
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 86400
    
    timestamps = _message_cache.get(user_key, [])
    pruned = [t for t in timestamps if t >= cutoff]
    
    if pruned != timestamps:
        _message_cache[user_key] = pruned
    
    return len(pruned)

USER_TICKETS_FILE = "user_tickets.json"

def increment_ticket_count(user_id):
    data = {}
    if os.path.exists(USER_TICKETS_FILE):
        try:
            with open(USER_TICKETS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            pass
    data[str(user_id)] = data.get(str(user_id), 0) + 1
    try:
        with open(USER_TICKETS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass
        
def get_ticket_count(user_id):
    if os.path.exists(USER_TICKETS_FILE):
        try:
            with open(USER_TICKETS_FILE, "r") as f:
                data = json.load(f)
                return data.get(str(user_id), 0)
        except Exception:
            pass
    return 0


# Warnings storage
WARNINGS_FILE = "warnings.json"

def load_warnings():
    if os.path.exists(WARNINGS_FILE):
        try:
            with open(WARNINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_warnings(data):
    try:
        with open(WARNINGS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving warnings: {e}")

def get_warnings(user_id):
    data = load_warnings()
    return data.get(str(user_id), {"count": 0, "entries": []})

def add_warning(user_id, moderator_id, reason=None):
    data = load_warnings()
    key = str(user_id)
    entry = {
        "moderator_id": moderator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason or ""
    }
    user_data = data.get(key, {"count": 0, "entries": []})
    user_data["count"] = user_data.get("count", 0) + 1
    user_data.setdefault("entries", []).append(entry)
    data[key] = user_data
    save_warnings(data)
    return user_data["count"]

def remove_warning(user_id, num: int = 1):
    """Remove the most recent `num` warnings for a user. Returns (new_count, removed_entries)."""
    if num <= 0:
        return get_warnings(user_id).get("count", 0), []

    data = load_warnings()
    key = str(user_id)
    user_data = data.get(key, {"count": 0, "entries": []})
    entries = user_data.get("entries", [])
    if not entries:
        return 0, []

    # Pop up to `num` most recent entries
    removed = []
    for _ in range(min(num, len(entries))):
        removed_entry = entries.pop()
        removed.append(removed_entry)

    user_data["entries"] = entries
    user_data["count"] = len(entries)
    if user_data["count"] <= 0:
        # Remove user key entirely if no warnings left
        if key in data:
            del data[key]
    else:
        data[key] = user_data

    save_warnings(data)
    return user_data.get("count", 0), removed


# Load environment variables
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
CATEGORY_ID = int(os.getenv('CATEGORY_ID', 0))
STAFF_ROLE_ID = int(os.getenv('STAFF_ROLE_ID', 0))
VOUCH_CHANNEL_ID = int(os.getenv('VOUCH_CHANNEL_ID', 0))
HELPER_CHANNEL_ID = int(os.getenv('HELPER_CHANNEL_ID', 0))

print(f"DEBUG: CATEGORY_ID={CATEGORY_ID}")
print(f"DEBUG: STAFF_ROLE_ID={STAFF_ROLE_ID}")
print(f"DEBUG: DISCORD_TOKEN loaded: {'YES' if bool(TOKEN) else 'NO'}")
print(f"DEBUG: .env file exists: {'YES' if os.path.exists('.env') else 'NO'}")

# Supabase Setup
SUPABASE_URL = os.getenv('SUPABASE_URL', '').replace('/rest/v1/', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

init_vouch_database()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY and SUPABASE_URL != "your_supabase_url":
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"WARNING: Supabase disabled because the configuration is invalid: {e}")

class Emojis:
    # Defaults
    CARRY = "⚔️"
    VOUCH = "⭐"
    STAFF = "🛡️"
    TICKET = "🎫"
    SUCCESS = "✅"
    WAITING = "⏳"
    GAME = "🎮"
    USER = "👤"
    INFO = "ℹ️"
    ARROW = "➔"
    LOCK = "🔒"
    ALS = AG = AC = UTD = AV = BL = SP = ARX = ASTD = AOL = AE = "🎮"
    CLAIM = UNCLAIM = REMIND = COMPLETE = LINK = PLUS = DIAMOND = GOAL = STATUS = "🔹"

    @classmethod
    def update(cls, bot: commands.Bot):
        game_emoji_aliases = {
            'ALS': {'als', 'animelaststand'},
            'AV': {'av', 'animevanguards'},
            'UTD': {'utd', 'utdx', 'universaltowerdefense'},
            'AE': {'ae', 'animeexpeditions'},
        }
        keys = [
            'CARRY', 'VOUCH', 'STAFF', 'TICKET', 'SUCCESS', 'WAITING', 'GAME', 'USER', 'INFO', 'ARROW', 'LOCK',
            'ALS', 'AG', 'AC', 'UTD', 'AV', 'BL', 'SP', 'ARX', 'ASTD', 'AOL', 'AE',
            'CLAIM', 'UNCLAIM', 'REMIND', 'COMPLETE', 'LINK', 'PLUS', 'DIAMOND', 'GOAL', 'STATUS'
        ]
        
        for key in keys:
            val = os.getenv(f'EMOJI_{key}')
            if not val:
                normalized_names = game_emoji_aliases.get(key, {key.lower()})
                emoji_obj = next(
                    (emoji for emoji in bot.emojis
                     if re.sub(r'[^a-z0-9]', '', emoji.name.lower()) in normalized_names),
                    None,
                )
                if emoji_obj:
                    setattr(cls, key, emoji_obj)
                continue
                
            if val.isdigit():
                emoji_id = int(val)
                emoji_obj = bot.get_emoji(emoji_id)
                if emoji_obj:
                    setattr(cls, key, emoji_obj)
                else:
                    # Fallback to a generic emoji instead of :p:
                    generic_fallbacks = {
                        'ALS': "🎮", 'AG': "🎮", 'AC': "🎮", 'UTD': "🎮", 'AV': "🎮", 'BL': "🎮", 'SP': "🎮", 'ARX': "🎮", 'ASTD': "🎮", 'AOL': "🎮", 'AE': "🎮",
                        'CARRY': "⚔️", 'VOUCH': "⭐", 'STAFF': "🛡️", 'TICKET': "🎫", 'SUCCESS': "✅", 'WAITING': "⏳", 'GAME': "🎮", 'USER': "👤", 'INFO': "ℹ️", 'ARROW': "➔", 'LOCK': "🔒",
                        'CLAIM': "🔹", 'UNCLAIM': "🔹", 'REMIND': "🔹", 'COMPLETE': "✅", 'LINK': "🔗", 'PLUS': "➕", 'DIAMOND': "💎", 'GOAL': "🎯", 'STATUS': "📊"
                    }
                    setattr(cls, key, generic_fallbacks.get(key, "🔹"))
            else:
                setattr(cls, key, val)

class VouchModal(discord.ui.Modal, title="Vouch Feedback"):
    stars = discord.ui.TextInput(
        label="Star Rating (1-5)",
        style=discord.TextStyle.short,
        placeholder="5",
        required=True,
        min_length=1,
        max_length=1,
        default="5"
    )
    feedback = discord.ui.TextInput(
        label="Feedback",
        style=discord.TextStyle.paragraph,
        placeholder="Thanks good carry...",
        required=True,
        max_length=150
    )

    def __init__(self, booster: discord.Member, game: str, user_id: int):
        super().__init__()
        self.booster = booster
        self.game = game
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        # Validate star rating
        try:
            star_count = int(self.stars.value)
            if star_count < 1 or star_count > 5:
                star_count = 5
        except ValueError:
            star_count = 5

        await interaction.response.defer(ephemeral=True)
        booster = self.booster
        game = self.game
        customer = interaction.user
        previous_total = get_total_vouches(booster.id)

        local_vouch_id = save_vouch_record(
            booster_id=booster.id,
            customer_id=customer.id,
            game=game,
            feedback=self.feedback.value,
            star_rating=star_count,
            ticket_id=interaction.channel.id,
            booster_name=booster.name,
            source='local',
        )

        vouch_saved = False
        if supabase:
            try:
                supabase.table("vouches").insert({
                    "booster_id": str(booster.id),
                    "customer_id": str(customer.id),
                    "game": game,
                    "booster_name": booster.name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "feedback": self.feedback.value,
                    "star_rating": star_count,
                    "ticket_id": str(interaction.channel.id),
                }).execute()
                vouch_saved = True
            except Exception as e:
                print(f"Error saving to Supabase: {e}")

        if not vouch_saved and local_vouch_id is None:
            add_bonus_vouches(booster.id, 1, game)

        if VOUCH_CHANNEL_ID != 0:
            vouch_channel = interaction.guild.get_channel(VOUCH_CHANNEL_ID)
            if vouch_channel:
                minimum_total = previous_total + 1
                total_vouches = get_total_vouches(booster.id, minimum_total)

                embed = create_vouch_embed(
                    customer, booster, game, self.feedback.value, total_vouches,
                    interaction.channel.id, star_rating=star_count
                )
                await vouch_channel.send(embed=embed)

        await interaction.followup.send(f"{Emojis.SUCCESS} Vouch registered! Closing ticket in 3 seconds...", ephemeral=False)
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete()
        except discord.errors.NotFound:
            pass
        except discord.errors.Forbidden:
            print("Missing permissions to delete the ticket channel.")

class CarryRequestModal(discord.ui.Modal, title="Carry Request Details"):
    username = discord.ui.TextInput(
        label="Your In-Game Username",
        placeholder="Enter your Roblox username...",
        required=True,
        min_length=3,
        max_length=50
    )
    help_with = discord.ui.TextInput(
        label="What do you need help with?",
        placeholder="Describe what you need (e.g. Carry to floor 50, Raid help...)",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=5,
        max_length=500
    )

    def __init__(self, game_id, game_name, method, parent_view):
        super().__init__()
        self.game_id = game_id
        self.game_name = game_name
        self.method = method
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await self.parent_view.finalize_ticket(interaction, self.method, self.username.value, self.help_with.value)

class TicketControlView(discord.ui.View):
    def __init__(self, customer_id: int = None, game_id: str = None):
        super().__init__(timeout=None)
        self.customer_id = customer_id
        self.game_id = game_id

    def _get_game(self, interaction, embed):
        if self.game_id:
            return self.game_id
        for field in embed.fields:
            if "Gamemode" in field.name:
                match = re.search(r'\((.*?)\)', field.value)
                if match:
                    return match.group(1).upper()
        return interaction.channel.name.split('-')[0].upper()

    def _get_user_id(self, embed):
        if self.customer_id:
            return self.customer_id
        match = re.search(r'<@!?(\d+)>', embed.description)
        if match:
            return int(match.group(1))
        return None

    def _get_status_index(self, embed):
        for i, field in enumerate(embed.fields):
            if "Status" in field.name:
                return i
        return len(embed.fields) - 1

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.green, custom_id="claim_button")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = interaction.message.embeds[0]
        game = self._get_game(interaction, embed)
        status_idx = self._get_status_index(embed)
        status_field = embed.fields[status_idx].value
        if "🟢" in status_field:
            await interaction.followup.send("❌ This ticket is already claimed!", ephemeral=True)
            return

        specific_role_id = GAME_ROLE_MAP.get(game.upper())
        has_role = any(role.id == specific_role_id for role in interaction.user.roles)
        
        if not has_role:
            allowed_roles = ["als helper", "av helper", "utd helper", "ae helper"]
            has_role = any(role.name.lower() in allowed_roles for role in interaction.user.roles)
        
        if not has_role and not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You do not have permission to claim this ticket. Only helpers can claim.", ephemeral=True)
            return

        staff = interaction.user
        embed.set_field_at(self._get_status_index(embed), name=f"{Emojis.STATUS} Status", value=f"🟢 **Claimed by {staff.mention}**", inline=False)
        
        specific_role_name = f"{game} Helper"
        specific_role = discord.utils.get(interaction.guild.roles, name=specific_role_name)
        if not specific_role:
            specific_role = next((r for r in interaction.guild.roles if r.name.lower() == specific_role_name.lower()), None)

        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        overwrites = interaction.channel.overwrites
        
        if specific_role:
            overwrites[specific_role] = discord.PermissionOverwrite(read_messages=False)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=False)
            
        overwrites[staff] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        await interaction.channel.edit(overwrites=overwrites)
        
        await interaction.edit_original_response(embed=embed)

    @discord.ui.button(label="Unclaim", style=discord.ButtonStyle.blurple, custom_id="unclaim_button")
    async def unclaim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = interaction.message.embeds[0]
        game = self._get_game(interaction, embed)
        status_idx = self._get_status_index(embed)
        status_field = embed.fields[status_idx].value
        if "🟢" not in status_field:
            await interaction.followup.send("❌ This ticket is not claimed!", ephemeral=True)
            return

        match = re.search(r'<@!?(\d+)>', status_field)
        claimer_id = int(match.group(1)) if match else None

        if claimer_id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Only the person who claimed this can unclaim it!", ephemeral=True)
            return

        embed.set_field_at(self._get_status_index(embed), name=f"{Emojis.STATUS} Status", value=f"🟡 **Waiting for claim**", inline=False)
        
        specific_role_id = GAME_ROLE_MAP.get(game.upper())
        specific_role = interaction.guild.get_role(specific_role_id) if specific_role_id else None
        
        if not specific_role:
            specific_role_name = f"{game} Helper"
            specific_role = discord.utils.get(interaction.guild.roles, name=specific_role_name)
            if not specific_role:
                specific_role = next((r for r in interaction.guild.roles if r.name.lower() == specific_role_name.lower()), None)

        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        overwrites = interaction.channel.overwrites
        if interaction.user in overwrites:
            del overwrites[interaction.user]
        if specific_role:
            overwrites[specific_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        elif staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        await interaction.channel.edit(overwrites=overwrites)
        
        await interaction.edit_original_response(embed=embed)

    @discord.ui.button(label="Close Request", style=discord.ButtonStyle.red, custom_id="close_button")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.delete()

    @discord.ui.button(label="Remind User", style=discord.ButtonStyle.secondary, custom_id="remind_button")
    async def remind_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"🔔 {interaction.user.mention} is waiting for you!", ephemeral=False)

    @discord.ui.button(label="Complete Run", style=discord.ButtonStyle.green, custom_id="complete_button")
    async def complete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = interaction.message.embeds[0]
        user_id = self._get_user_id(embed)
        status_idx = self._get_status_index(embed)
        status_field = embed.fields[status_idx].value
        if "🟢" not in status_field:
            await interaction.followup.send("❌ This ticket must be claimed first!", ephemeral=True)
            return
            
        if interaction.user.id != user_id:
            await interaction.followup.send("❌ Only the customer can complete the run!", ephemeral=True)
            return

        match = re.search(r'<@!?(\d+)>', status_field)
        if not match:
            await interaction.followup.send("❌ Could not determine which helper claimed this ticket.", ephemeral=True)
            return
            
        claimer_id = int(match.group(1))

        # Include claimer_id in the status so we can parse it in vouch_button
        embed.set_field_at(self._get_status_index(embed), name=f"{Emojis.STATUS} Status", value=f"✅ **Run Completed by <@{claimer_id}>**", inline=False)
        
        # Use a dedicated view for the completed state to ensure persistence
        view = CompletedTicketView(claimer_id=claimer_id, customer_id=user_id, game=self._get_game(interaction, embed))
        await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Vouch Booster", style=discord.ButtonStyle.green, custom_id="vouch_button")
    async def vouch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        user_id = self._get_user_id(embed)
        game = self._get_game(interaction, embed)
        
        if interaction.user.id != user_id:
            await interaction.response.send_message("❌ Only the customer can vouch!", ephemeral=True)
            return

        status_idx = self._get_status_index(embed)
        status_value = embed.fields[status_idx].value
        match = re.search(r'<@!?(\d+)>', status_value)
        if match:
            booster_id = int(match.group(1))
            booster = interaction.guild.get_member(booster_id)
        else:
            booster = None

        if not booster:
            try:
                booster = await interaction.guild.fetch_member(booster_id)
            except Exception:
                await interaction.response.send_message("❌ Could not determine booster.", ephemeral=True)
                return

        modal = VouchModal(booster, game, user_id)
        await interaction.response.send_modal(modal)


class CompletedTicketView(discord.ui.View):
    def __init__(self, claimer_id: int = None, customer_id: int = None, game: str = None):
        super().__init__(timeout=None)
        self.claimer_id = claimer_id
        self.customer_id = customer_id
        self.game = game

    def _get_data(self, interaction, embed):
        customer_id = self.customer_id
        if not customer_id:
            match = re.search(r'<@!?(\d+)>', embed.description)
            customer_id = int(match.group(1)) if match else None
        
        claimer_id = self.claimer_id
        if not claimer_id:
            status_field = next((f.value for f in embed.fields if "Status" in f.name), "")
            match = re.search(r'<@!?(\d+)>', status_field)
            claimer_id = int(match.group(1)) if match else None
            
        game = self.game
        if not game:
            for field in embed.fields:
                if "Gamemode" in field.name:
                    match = re.search(r'\((.*?)\)', field.value)
                    game = match.group(1).upper() if match else None
        
        if not game:
            game = interaction.channel.name.split('-')[0].upper()
            
        return customer_id, claimer_id, game

    @discord.ui.button(label="Vouch Booster", style=discord.ButtonStyle.green, custom_id="vouch_button_completed")
    async def vouch_button_completed(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        customer_id, booster_id, game = self._get_data(interaction, embed)
        
        if interaction.user.id != customer_id:
            await interaction.response.send_message("❌ Only the customer can vouch!", ephemeral=True)
            return

        if not booster_id:
            await interaction.response.send_message("❌ Could not determine booster.", ephemeral=True)
            return

        booster = interaction.guild.get_member(booster_id)
        if not booster:
            try:
                booster = await interaction.guild.fetch_member(booster_id)
            except Exception:
                await interaction.response.send_message("❌ Could not find booster in the server.", ephemeral=True)
                return

        modal = VouchModal(booster, game, customer_id)
        await interaction.response.send_modal(modal)

class JoinMethodView(discord.ui.View):
    def __init__(self, game_id: str, game_name: str):
        super().__init__(timeout=60)
        self.game_id = game_id
        self.game_name = game_name

    @discord.ui.button(label="Join by Links", style=discord.ButtonStyle.green, custom_id="join_links")
    async def join_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CarryRequestModal(self.game_id, self.game_name, "Join by Links", self))

    @discord.ui.button(label="Add Helper", style=discord.ButtonStyle.blurple, custom_id="add_helper")
    async def add_helper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CarryRequestModal(self.game_id, self.game_name, "Add Helper", self))

    @discord.ui.button(label="💎 Trade Coming Soon", style=discord.ButtonStyle.gray, custom_id="trade_soon", disabled=True)
    async def trade_soon(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    async def finalize_ticket(self, interaction: discord.Interaction, method: str, username: str, goal: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(CATEGORY_ID)
        staff_role = guild.get_role(STAFF_ROLE_ID)

        if not category:
            await interaction.followup.send("❌ Category not configured.", ephemeral=True)
            return

        # Determine specific helper role
        specific_role_id = GAME_ROLE_MAP.get(self.game_id)
        specific_role = guild.get_role(specific_role_id) if specific_role_id else None
        
        if not specific_role:
            specific_role_name = f"{self.game_id} Helper"
            specific_role = discord.utils.get(guild.roles, name=specific_role_name)
            if not specific_role:
                specific_role = next((r for r in guild.roles if r.name.lower() == specific_role_name.lower()), None)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if specific_role:
            overwrites[specific_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        elif staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_num = datetime.now().strftime("%H%M") 
        
        channel = await guild.create_text_channel(
            name=f"{self.game_id}-{user.name}",
            category=category,
            overwrites=overwrites
        )

        increment_ticket_count(user.id)

        await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)

        embed = V2Embed(
            title=f"{Emojis.TICKET} Ticket #{ticket_num}",
            description=f"{user.mention} — **Your carry request is active!**"
        )
        
        embed.add_field(name=f"{Emojis.USER} Roblox Username", value=f"```\n{username}\n```", inline=False)
        embed.add_field(name=f"{Emojis.GAME} Gamemode", value=f"```\n{self.game_name}\n```", inline=False)
        embed.add_field(name=f"{Emojis.GOAL} Goal", value=f"```\n{goal}\n```", inline=False)
        embed.add_field(name=f"{Emojis.LINK} Join Method", value=f"```\n{method}\n```", inline=False)
        embed.add_field(name=f"{Emojis.STATUS} Status", value=f"🟡 **Waiting for claim**", inline=False)
        
        embed.set_footer(text="PARADOX Carry Service • Premium Edition")
        
        # Use Paradox logo as thumbnail
        ticket_files = []
        logo_path = get_asset_path("setup_header.png")
        if os.path.exists(logo_path):
            logo_file = discord.File(logo_path, filename="paradox_logo.png")
            embed.set_thumbnail(url="attachment://paradox_logo.png")
            ticket_files.append(logo_file)
        else:
            embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
        
        ping_content = f"{user.mention}"
        if specific_role:
            ping_content += f" {specific_role.mention}"
        elif staff_role:
            ping_content += f" {staff_role.mention}"
        
        await channel.send(content=ping_content, embed=embed, files=ticket_files if ticket_files else [], view=TicketControlView(customer_id=user.id, game_id=self.game_id))

class ParadoxTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(label="Anime Last Stand (ALS)", emoji=Emojis.ALS, value="ALS"),
            discord.SelectOption(label="Anime Vanguards (AV)", emoji=Emojis.AV, value="AV"),
            discord.SelectOption(label="Universal Tower Defense (UTD)", emoji=Emojis.UTD, value="UTD"),
            discord.SelectOption(label="Anime Expeditions (AE)", emoji=Emojis.AE, value="AE"),
        ]
        self.select = discord.ui.Select(
            custom_id="paradox_selector",
            placeholder="Select a game to start your ticket!",
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        try:
            # Check messages requirement (exempt admins and staff)
            is_staff = interaction.user.guild_permissions.administrator or any(role.id == STAFF_ROLE_ID for role in interaction.user.roles)
            if not is_staff:
                msg_count = get_message_count_last_24h(interaction.user.id)
                if msg_count < 15:
                    await interaction.response.send_message(
                        f"❌ **Ticket Access Denied**\n\n"
                        f"You must have sent at least **15 messages** in the server in the last 24 hours to open a ticket.\n"
                        f"Current messages sent: **{msg_count}/15**\n\n"
                        f"Message count resets on a rolling 24-hour basis.",
                        ephemeral=True
                    )
                    return

            game_id = self.select.values[0]
            game_name = [opt.label for opt in self.select.options if opt.value == game_id][0]
            if CATEGORY_ID == 0:
                await interaction.response.send_message("❌ Category not configured.", ephemeral=True)
                return
            
            embed = V2Embed(
                title=f"{Emojis.LINK} Select Joining Method",
                description="How would you like to join the helper?"
            )
            embed.add_field(name=f"{Emojis.GAME} Game", value=f"```\n{game_name}\n```", inline=True)
            embed.add_field(name=f"{Emojis.STATUS} Gamemode", value=f"```\n{game_id}\n```", inline=True)
            
            # Use the bot's current Discord avatar so it stays in sync automatically.
            files = []
            embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
            game_image_names = {
                "ALS": "als.webp",
                "AV": "av.png",
                "UTD": "utd.jpg",
                "AE": "ae.jpg",
            }
            game_image_name = game_image_names.get(game_id)
            game_image_path = get_asset_path(game_image_name) if game_image_name else None
            if game_image_path:
                files.append(discord.File(game_image_path, filename=game_image_name))
                embed.set_image(url=f"attachment://{game_image_name}")
            
            # Using ephemeral=True as requested for initial view
            await interaction.response.send_message(
                embed=embed, 
                files=files,
                view=JoinMethodView(game_id, game_name), 
                ephemeral=True
            )
        except Exception as e:
            print(f"DEBUG: ParadoxTicketView Error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)

class HelperApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(label="Anime Last Stand (ALS)", emoji=Emojis.ALS, value="ALS"),
            discord.SelectOption(label="Anime Vanguards (AV)", emoji=Emojis.AV, value="AV"),
            discord.SelectOption(label="Universal Tower Defense (UTD)", emoji=Emojis.UTD, value="UTD"),
            discord.SelectOption(label="Anime Expeditions (AE)", emoji=Emojis.AE, value="AE"),
        ]
        self.select = discord.ui.Select(
            custom_id="helper_selector",
            placeholder="Select your specialty!",
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        game_id = self.select.values[0]
        game_name = [opt.label for opt in self.select.options if opt.value == game_id][0]
        
        if game_id in ["ALS", "AV", "UTD", "AE"]:
            # Start Application Flow
            await interaction.response.send_message(f"✅ **Application Started!** Please check your DMs to proceed.", ephemeral=True)
            asyncio.create_task(start_application(interaction.user, game_id, game_name))
            return

        embed = V2Embed(
            title=f"{Emojis.STAFF} Helper Application",
            description=f"You are applying for the position of **{game_name} Helper**.\n\nPlease answer the questions below to proceed."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class InterviewTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="close_interview")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 Closing ticket in 3 seconds...")
        await asyncio.sleep(3)
        await interaction.channel.delete()

class ApplicationReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.role_mapping = {
            "Anime Last Stand (ALS)": 1500199051952656578,
            "Anime Vanguards (AV)": 1500198955940712468,
            "Universal Tower Defense (UTD)": 1505300013604147332,
            "Anime Expeditions (AE)": 1541834030717075457
        }

    def parse_data(self, interaction: discord.Interaction):
        try:
            embed = interaction.message.embeds[0]
            title = embed.title
            # Match after the 's (possessive) and between quotes
            game_match = re.search(r"'s '(.*) Helper Application'", title)
            if not game_match:
                # Fallback: just match the last pair of quotes if possible
                game_match = re.search(r"'([^']*) Helper Application'", title)
            
            game_name = game_match.group(1) if game_match else "Unknown"
            
            desc = embed.description
            # Try to match both with and without backticks
            user_match = re.search(r"UserId: `?(\d+)`?", desc)
            applicant_id = int(user_match.group(1)) if user_match else None
            
            return applicant_id, game_name
        except Exception as e:
            print(f"DEBUG: Parse Error: {e}")
            return None, None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green, custom_id="app_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"DEBUG: Accept button clicked by {interaction.user}")
        try:
            await interaction.response.defer()
            applicant_id, game_name = self.parse_data(interaction)
            print(f"DEBUG: Parsed data - Applicant: {applicant_id}, Game: {game_name}")
            
            if not applicant_id:
                print(f"DEBUG: Could not parse applicant ID from description.")
                return

            guild = interaction.guild
            applicant = guild.get_member(applicant_id)
            if not applicant:
                try:
                    applicant = await guild.fetch_member(applicant_id)
                except Exception:
                    print(f"DEBUG: Could not find member {applicant_id} in guild.")
            
            # Give role
            role_id = self.role_mapping.get(game_name)
            role_given = False
            role = None
            if role_id:
                role = guild.get_role(role_id)
                if not role:
                    try:
                        role = await guild.fetch_role(role_id)
                    except Exception as e:
                        print(f"DEBUG: Role Fetch Error: {e}")
                
                if role and applicant:
                    try:
                        await applicant.add_roles(role)
                        role_given = True
                    except Exception as e:
                        print(f"DEBUG: Role Assignment Error: {e}")
                else:
                    print(f"DEBUG: Role {role_id} or Applicant {applicant_id} not found.")
            else:
                print(f"DEBUG: No role mapping found for game name: '{game_name}'")

            # DM User
            embed = V2Embed(
                title="Application accepted",
                description=f"Congratulations! Your application for **{game_name}** has been accepted.\n\n" + (f"✅ **You have been given the {game_name} role!**" if role_given else ""),
                color=discord.Color.green()
            )
            try:
                if applicant:
                    await applicant.send(embed=embed)
            except Exception as e:
                print(f"DEBUG: DM Send Error: {e}")
                
            # Update staff message
            original_embed = interaction.message.embeds[0]
            original_embed.color = discord.Color.green()
            original_embed.add_field(name="Status", value=f"✅ Accepted by {interaction.user.mention}", inline=False)
            if role_given and role:
                original_embed.add_field(name="Role Granted", value=f"✅ {role.mention} has been added to {applicant.mention}", inline=False)
            await interaction.edit_original_response(embed=original_embed, view=None)
        except Exception as e:
            print(f"DEBUG: Accept Button Error: {e}")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="app_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        applicant_id, game_name = self.parse_data(interaction)
        if not applicant_id: return

        guild = interaction.guild
        applicant = guild.get_member(applicant_id) or await guild.fetch_member(applicant_id)
        
        embed = V2Embed(
            title="Application Rejected",
            description=f"Your application for `{game_name} Helper Application` has been rejected by {interaction.user.mention}",
            color=discord.Color.red()
        )
        try:
            if applicant: await applicant.send(embed=embed)
        except Exception:
            pass
            
        # Update staff message
        original_embed = interaction.message.embeds[0]
        original_embed.color = discord.Color.red()
        original_embed.add_field(name="Status", value=f"❌ Rejected by {interaction.user.mention}", inline=False)
        await interaction.edit_original_response(embed=original_embed, view=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.secondary, custom_id="app_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        applicant_id, game_name = self.parse_data(interaction)
        if not applicant_id: return
        
        guild = interaction.guild
        applicant = guild.get_member(applicant_id) or await guild.fetch_member(applicant_id)
        
        category = guild.get_channel(CATEGORY_ID)
        if not category:
            await interaction.followup.send("❌ Ticket category not configured.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            applicant: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        channel = await guild.create_text_channel(
            name=f"interview-{applicant.name if applicant else applicant_id}",
            category=category,
            overwrites=overwrites
        )
        
        await interaction.followup.send(f"✅ Interview ticket created: {channel.mention}", ephemeral=True)
        
        embed = V2Embed(
            title="Interview Started",
            description=f"Hello {applicant.mention if applicant else 'Applicant'}, {interaction.user.mention} would like to interview you regarding your **{game_name}** application."
        )
        await channel.send(content=f"{applicant.mention if applicant else ''} {interaction.user.mention}", embed=embed, view=InterviewTicketView())

class YesNoView(discord.ui.View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=120)
        self.user = user
        self.value = None

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id: return
        self.value = True
        await interaction.response.edit_message(content="**Question answered**\nYou chose option: `Yes`", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id: return
        self.value = False
        await interaction.response.edit_message(content="**Question answered**\nYou chose option: `No`", embed=None, view=None)
        self.stop()

async def start_application(user: discord.Member, game_id: str, game_name: str):
    try:
        # Initial DM
        start_embed = V2Embed(
            title="Application Started",
            description="Please answer the questions below, either by clicking on the dropdown menus or sending a message to the bot.",
            color=discord.Color.green()
        )
        await user.send(embed=start_embed)
    except discord.Forbidden:
        return # User has DMs closed

    if game_id == "ALS":
        questions = [
            {"text": "1. Can you consistently solo the hardest current Infinity/Portal stages or Raid stages and Caverns by yourself?", "type": "yesno"},
            {"text": "2. Send a screenshot of your best units (images only).", "type": "image"},
            {"text": "3. Do you have a maxed-out meta farming unit and a top-tier DPS unit ready for high-level carries?", "type": "yesno"},
            {"text": "4. Will you be loyal to us?", "type": "yesno"},
        ]
    elif game_id == "AV":
        questions = [
            {"text": "1. What level are you in Anime Vanguard?", "type": "text"},
            {"text": "2. What is your best team ( Please provide an screenshot of including your memorias and familiars)", "type": "image"},
            {"text": "3. How active can u be daily on discord?", "type": "text"},
            {"text": "4. Are you able to Solo the new hardest Content?", "type": "yesno"},
            {"text": "5. What floor number are you on for all the elements?", "type": "text"},
            {"text": "6. Are you able to carry to carry Cid raid?", "type": "yesno"},
        ]
    elif game_id == "UTD":
        questions = [
            {"text": "1. How much time can you spend helping a day?", "type": "text"},
            {"text": "2. Do you have all content unlocked? (story, raids, legend stages, etc.)", "type": "yesno"},
            {"text": "3. Are you lvl 50? (to have all 6 unit slots)", "type": "yesno"},
            {"text": "4. Can you solo most of the game content?", "type": "yesno"},
        ]
    elif game_id == "AE":
        questions = [
            {"text": "1. Can you successfully solo high-level Raids or late-game Expeditions stages on your own?", "type": "yesno"},
            {"text": "2. Do you have an optimized team build ready for multi-lane map coverage and boss melting?", "type": "yesno"},
            {"text": "3. Do you actively use and understand advanced mechanics like multi-lane map positioning, Stat Anvils, and Research Tree progression to maximize your unit damage?", "type": "yesno"},
            {"text": "4. Can you clear challenge restrictions (such as no-money-unit runs or strict skull modifier trials) for end-game rewards?", "type": "yesno"},
            {"text": "5. Provide proof of your progress (e.g., screenshot showing a solo completion or your top-tier unit loadout).", "type": "image"},
        ]
    else:
        return

    answers = {}
    start_time = datetime.now()
    
    def check(m):
        return m.author.id == user.id and isinstance(m.channel, discord.DMChannel)

    for i, q in enumerate(questions):
        q_num_text = q['text']
        embed = V2Embed(
            title=f"{game_name} Helper Application",
            description=f"**{q_num_text}**\n\nTo answer this question, please send a message to the bot with your response." if q['type'] != "yesno" else f"**{q_num_text}**"
        )
        embed.set_footer(text="Type '!end' to cancel the application.")
        
        if q['type'] == "yesno":
            view = YesNoView(user)
            msg = await user.send(embed=embed, view=view)
            await view.wait()
            if view.value is None:
                await user.send("❌ Application timed out.")
                return
            answers[i+1] = "Yes" if view.value else "No"
        elif q['type'] == "text":
            await user.send(embed=embed)
            try:
                msg = await bot.wait_for('message', check=check, timeout=600) # 10 mins
                if msg.content.lower().startswith("!end"):
                    await user.send("❌ Application cancelled.")
                    return
                answers[i+1] = msg.content
            except asyncio.TimeoutError:
                await user.send("❌ Application timed out.")
                return
        elif q['type'] == "image":
            await user.send(embed=embed)
            try:
                while True:
                    msg = await bot.wait_for('message', check=check, timeout=600)
                    if msg.content.lower().startswith("!end"):
                        await user.send("❌ Application cancelled.")
                        return
                    image_attachment = next(
                        (attachment for attachment in msg.attachments
                         if attachment.content_type and attachment.content_type.startswith("image/")),
                        None,
                    )
                    if image_attachment:
                        answers[i+1] = image_attachment.url
                        break
                    else:
                        await user.send("❌ Please upload an image file or type '!end' to cancel.")
            except asyncio.TimeoutError:
                await user.send("❌ Application timed out.")
                return

    # Final submission
    submit_embed = V2Embed(
        title="Application submitted.",
        description="Your application has been submitted.",
        color=discord.Color.green()
    )
    await user.send(embed=submit_embed)

    # Send to staff
    if HELPER_CHANNEL_ID != 0:
        staff_channel = bot.get_channel(HELPER_CHANNEL_ID)
        if staff_channel:
            duration = int((datetime.now() - start_time).total_seconds())
            
            # Format description based on questions
            desc_parts = []
            for i, q in enumerate(questions):
                q_text = q['text'].split('\n')[0] # Get the first line of the question
                extra_info = q['text'].split('\n')[1] if '\n' in q['text'] else ""
                
                part = f"**{q_text}**\n\n"
                if extra_info:
                    part += f"**{extra_info}**\n"
                
                if q['type'] == "image":
                    part += f"[View attachment]({answers[i+1]})\n\n"
                else:
                    part += f"{answers[i+1]}\n\n"
                desc_parts.append(part)
            
            desc_parts.append("**Submission stats**\n")
            desc_parts.append(f"UserId: `{user.id}`\n")
            desc_parts.append(f"Username: `{user.name}`\n")
            desc_parts.append(f"User: {user.mention}\n")
            desc_parts.append(f"Duration: `{duration}s`")
            
            if isinstance(user, discord.Member) and user.joined_at:
                joined_delta = datetime.now(timezone.utc) - user.joined_at
                days = joined_delta.days
                if days == 0: joined_text = "today"
                elif days == 1: joined_text = "a day ago"
                else: joined_text = f"{days} days ago"
                desc_parts.append(f"\nJoined guild: `{joined_text}`")

            review_embed = V2Embed(
                title=f"{user.name}'s '{game_name} Helper Application' Application Submitted",
                description="".join(desc_parts),
                color=0x2b2d31
            )
            review_embed.set_thumbnail(url=user.display_avatar.url)
            
            await staff_channel.send(content="<@&1500179933073375232>", embed=review_embed, view=ApplicationReviewView())

# ──────────────────────────────────────────
# PING ROLE SELF-ASSIGN SYSTEM
# ──────────────────────────────────────────

PING_ROLES = {
    "announcements": "Announcement Pings",
    "giveaways":     "Giveaway Pings",
    "events":        "Event Pings",
}

class PingRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _toggle_role(self, interaction: discord.Interaction, role_name: str, emoji: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try:
                role = await guild.create_role(
                    name=role_name,
                    mentionable=True,
                    reason="Auto-created by ping role system"
                )
            except discord.Forbidden:
                await interaction.followup.send("❌ I don't have permission to create roles!", ephemeral=True)
                return
        if role in member.roles:
            await member.remove_roles(role, reason="Ping role self-removed")
            await interaction.followup.send(
                f"{emoji} Removed **{role_name}** — you will no longer receive these pings.",
                ephemeral=True
            )
        else:
            await member.add_roles(role, reason="Ping role self-assigned")
            await interaction.followup.send(
                f"{emoji} Added **{role_name}** — you will now receive these pings!",
                ephemeral=True
            )

    @discord.ui.button(label="📢 Announcements", style=discord.ButtonStyle.blurple, custom_id="ping_announcements")
    async def announcements(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_role(interaction, PING_ROLES["announcements"], "📢")

    @discord.ui.button(label="🎉 Giveaways", style=discord.ButtonStyle.green, custom_id="ping_giveaways")
    async def giveaways(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_role(interaction, PING_ROLES["giveaways"], "🎉")

    @discord.ui.button(label="🎊 Events", style=discord.ButtonStyle.red, custom_id="ping_events")
    async def events(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_role(interaction, PING_ROLES["events"], "🎊")

# ============================================================================
# ONLINE HELPERS TRACKING
# ============================================================================
ONLINE_HELPERS_MESSAGE_ID = None  # Will store the message ID of the online helpers embed
ONLINE_HELPERS_CHANNEL_ID = 1544262915581022279  # Default channel for online helpers list
ONLINE_HELPERS_CONFIG_FILE = os.path.join(BASE_DIR, "online_helpers_config.json")

GAME_HELPER_ROLES = {
    "ALS": 1500199147859476604,
    "AV": 1500198955940712468,
    "UTD": 1505300013604147332,
    "AE": 1541834030717075457,
}

def load_online_helpers_config():
    """Load online helpers message ID and channel ID from file."""
    global ONLINE_HELPERS_MESSAGE_ID, ONLINE_HELPERS_CHANNEL_ID
    try:
        if os.path.exists(ONLINE_HELPERS_CONFIG_FILE):
            with open(ONLINE_HELPERS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                ONLINE_HELPERS_MESSAGE_ID = int(data.get("message_id", 0)) or None
                # Only override channel ID if different from default
                loaded_channel = int(data.get("channel_id", 0)) or None
                if loaded_channel:
                    ONLINE_HELPERS_CHANNEL_ID = loaded_channel
    except Exception as e:
        print(f"Error loading online helpers config: {e}")

def save_online_helpers_config():
    """Save online helpers message ID and channel ID to file."""
    try:
        data = {
            "message_id": ONLINE_HELPERS_MESSAGE_ID or 0,
            "channel_id": ONLINE_HELPERS_CHANNEL_ID or 0
        }
        with open(ONLINE_HELPERS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error saving online helpers config: {e}")

async def get_online_helpers_by_game(guild: discord.Guild):
    """Get a dictionary of online helpers organized by game."""
    online_helpers = {game: [] for game in GAME_HELPER_ROLES.keys()}
    
    try:
        # Get all roles from the guild
        guild_role_ids = {role.id for role in guild.roles}
        
        for member in guild.members:
            if member.bot:
                continue
            
            # Check if member is online (exclude offline/invisible)
            if member.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd):
                # Get member's role IDs
                member_role_ids = {role.id for role in member.roles}
                
                # Check each game role
                for game, role_id in GAME_HELPER_ROLES.items():
                    # Only proceed if the role exists in the guild
                    if role_id in guild_role_ids:
                        # Check if member has this specific role
                        if role_id in member_role_ids:
                            online_helpers[game].append(member)
                            print(f"DEBUG: {member.name} ({member.id}) has {game} helper role and is online")
    except Exception as e:
        print(f"Error fetching online helpers: {e}")
        import traceback
        traceback.print_exc()
    
    return online_helpers

async def create_online_helpers_embed(guild: discord.Guild):
    """Create an embed showing online helpers by game."""
    online_helpers = await get_online_helpers_by_game(guild)
    
    # Game emojis for better visual appeal
    game_emojis = {
        "ALS": "⚔️",
        "AV": "🎯",
        "UTD": "🗼",
        "AE": "🌟"
    }
    
    game_names = {
        "ALS": "Anime Last Stand",
        "AV": "Anime Vanguards",
        "UTD": "Universal Tower Defense",
        "AE": "Anime Expeditions"
    }
    
    # Calculate total online helpers
    total_online = sum(len(helpers) for helpers in online_helpers.values())
    
    embed = V2Embed(
        title="🟢 ONLINE HELPERS",
        description=f"**{total_online}** helpers currently available to assist with carries\n━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.green()
    )
    
    for game in ["ALS", "AV", "UTD", "AE"]:
        helpers = online_helpers.get(game, [])
        emoji = game_emojis.get(game, "•")
        name = game_names.get(game, game)
        
        if helpers:
            # Sort helpers by name
            sorted_helpers = sorted(helpers, key=lambda m: m.name)
            helper_text = "\n".join([f"  ✓ {h.mention}" for h in sorted_helpers])
            embed.add_field(
                name=f"{emoji} {game} - {name}",
                value=f"```\n{helper_text}\n```\n**Online:** {len(helpers)}",
                inline=False
            )
        else:
            embed.add_field(
                name=f"{emoji} {game} - {name}",
                value="```\nNo helpers online\n```\n**Online:** 0",
                inline=False
            )
    
    embed.set_footer(text="🔄 Updates in real-time • Last updated")
    embed.timestamp = discord.utils.utcnow()
    return embed

class ParadoxBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        # Enable presences for online helpers tracking
        intents.presences = True
        # Disable voice state to reduce overhead if not used
        intents.voice_states = False
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.invite_cache = {}  # guild_id -> {invite_code: uses}
        self.invite_tracker = {}  # user_id -> {"joined": [], "left": []}

    async def setup_hook(self):
        self.add_view(ParadoxTicketView())
        self.add_view(HelperApplicationView())
        self.add_view(ApplicationReviewView())
        self.add_view(PingRoleView())
        self.add_view(TicketControlView())
        self.add_view(CompletedTicketView())
        self.add_view(ParadoxTicketView())
        self.add_view(HelperApplicationView())
        
        # Load online helpers config
        load_online_helpers_config()
        
        # Load initial message cache from disk
        global _message_cache
        _message_cache = load_user_messages()
        
        # Start background save task
        self.loop.create_task(periodic_save_messages())
        
        # Start online helpers periodic update task
        self.loop.create_task(self.periodic_update_online_helpers())

    async def periodic_update_online_helpers(self):
        """Periodically update the online helpers list every 5 minutes."""
        global ONLINE_HELPERS_MESSAGE_ID, ONLINE_HELPERS_CHANNEL_ID
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                if ONLINE_HELPERS_MESSAGE_ID and ONLINE_HELPERS_CHANNEL_ID:
                    channel = self.get_channel(ONLINE_HELPERS_CHANNEL_ID)
                    if channel:
                        try:
                            message = await channel.fetch_message(ONLINE_HELPERS_MESSAGE_ID)
                            guild = channel.guild
                            embed = await create_online_helpers_embed(guild)
                            await message.edit(embed=embed)
                            print(f"✅ Online helpers list updated (periodic)")
                        except discord.NotFound:
                            print("Online helpers message not found, will recreate on next setup")
                            ONLINE_HELPERS_MESSAGE_ID = None
                            save_online_helpers_config()
                        except Exception as e:
                            print(f"Error updating online helpers: {e}")
                # Update every 5 minutes (300 seconds)
                await asyncio.sleep(300)
            except Exception as e:
                print(f"Error in periodic_update_online_helpers: {e}")
                await asyncio.sleep(300)

    async def close(self):
        # Save message cache before closing
        try:
            global _message_cache
            if _message_cache:
                save_user_messages(_message_cache)
        except Exception as e:
            print(f"Error saving message cache on shutdown: {e}")
        
        try:
            channel = self.get_channel(1504584461151375461) or await self.fetch_channel(1504584461151375461)
            if channel:
                embed = V2Embed(
                    title="🛠️ Bot Update & Changes",
                    description=(
                        "**Status Update:**\n\n"
                        "**1. Maintenance Mode**\n\n"
                        "• The bot is going offline for changes and maintenance.\n"
                        "• We'll be back online as soon as possible!\n\n"
                        "Paradox Development Team"
                    ),
                    color=discord.Color.orange()
                )
                await channel.send(embed=embed)
        except Exception as e:
            print(f"Error sending shutdown message: {e}")
        await super().close()

    async def ensure_bot_role(self, guild: discord.Guild):
        """Ensure a dedicated bot role exists and assign it to the bot member.

        Notes:
        - Requires the bot to have Manage Roles permission to create/assign roles.
        - If the bot lacks Manage Roles, this will silently return.
        """
        role_name = "Paradox Bot"
        try:
            role = discord.utils.get(guild.roles, name=role_name)
            me = guild.me or await guild.fetch_member(self.user.id)

            # Need manage_roles to create or assign roles
            if not guild.me.guild_permissions.manage_roles:
                return

            if not role:
                perms = discord.Permissions()
                perms.update(
                    manage_channels=True,
                    manage_roles=True,
                    manage_messages=True,
                    send_messages=True,
                    view_channel=True,
                    read_message_history=True,
                    embed_links=True,
                    attach_files=True
                )
                role = await guild.create_role(name=role_name, permissions=perms, reason="Create dedicated bot role with required permissions")

            if role not in me.roles:
                await me.add_roles(role, reason="Assign dedicated bot role")
        except Exception as e:
            print(f"DEBUG: ensure_bot_role failed for guild {guild.id}: {e}")

    async def on_ready(self):
        global WELCOME_ENABLED
        WELCOME_ENABLED = load_welcome_settings()
        print(f"Bot logged in as {self.user}")
        await set_bot_avatar_from_asset(self)
        
        # Send Online Message (async, non-blocking)
        try:
            channel = self.get_channel(1504584461151375461) or await self.fetch_channel(1504584461151375461)
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
        except Exception as e:
            print(f"Error sending online message: {e}")

        Emojis.update(self)
        print(f"Active category: {CATEGORY_ID}")
        
        # Lightweight initialization - lazy load invites on first member join instead
        # This significantly reduces CPU on startup for web hosting
        print("✅ Bot ready (invite tracking: lazy-loaded)")
        
        # Ensure bot role in first guild only (not all guilds at startup)
        if self.guilds:
            try:
                await self.ensure_bot_role(self.guilds[0])
            except Exception:
                pass

    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        
        # Give auto roles to new members
        for role_id in get_auto_roles():
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role)
                except Exception as e:
                    print(f"DEBUG: Failed to add auto role {role_id}: {e}")

        if WELCOME_ENABLED.get(guild.id, False):
            welcome_channel_id = get_welcome_channel_id_for_guild(guild.id)
            welcome_channel = guild.get_channel(welcome_channel_id)
            if welcome_channel and isinstance(welcome_channel, discord.TextChannel):
                welcome_file = None
                welcome_banner = get_asset_path("yuji.png")
                if welcome_banner and os.path.exists(welcome_banner):
                    welcome_file = discord.File(welcome_banner, filename="welcome_banner.png")

                embed = V2Embed(
                    title="Welcome to Paradox Guild",
                    description=(
                        f"**Welcome, {member.mention}!**\n\n"
                        "We’re glad you’re here.\n"
                        "Take a moment to review the server rules and get familiar with the community."
                    ),
                    color=discord.Color.blurple()
                )
                embed.add_field(
                    name="Server Guides",
                    value="Check the rules, ticket channels, and helper applications in the server.\n\nIf you are interested in helping the community, visit the #helper-application channel and submit your application. A staff member will review it shortly after.",
                    inline=False
                )
                if member.avatar:
                    embed.set_thumbnail(url=member.display_avatar.url)
                if welcome_file:
                    embed.set_image(url="attachment://welcome_banner.png")
                    await welcome_channel.send(content=f"{member.mention} has joined the server!", file=welcome_file, embed=embed)
                else:
                    await welcome_channel.send(content=f"{member.mention} has joined the server!", embed=embed)

        # Lazy load invites only if cache is empty for this guild (reduces CPU)
        if guild.id not in self.invite_cache:
            try:
                new_invites = await guild.invites()
                self.invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
            except Exception:
                return
        else:
            # Use cached invites if available
            try:
                new_invites = await guild.invites()
            except Exception:
                return
        
        old_cache = self.invite_cache.get(guild.id, {})
        used_invite = None
        for inv in new_invites:
            if old_cache.get(inv.code, 0) < inv.uses:
                used_invite = inv
                break
        # Update cache
        self.invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
        if used_invite and used_invite.inviter:
            inviter_id = str(used_invite.inviter.id)
            data = self.invite_tracker.setdefault(inviter_id, {"joined": [], "left": []})
            if member.id not in data["joined"]:
                data["joined"].append(member.id)
            # Remove from left list if they rejoined
            if member.id in data["left"]:
                data["left"].remove(member.id)

    async def on_member_remove(self, member: discord.Member):
        # Mark this member as having left in whoever invited them
        for inviter_id, data in self.invite_tracker.items():
            if member.id in data["joined"] and member.id not in data["left"]:
                data["left"].append(member.id)
                break

    async def on_message(self, message):
        global _last_message_time, _keyword_cooldowns
        
        if message.author.bot:
            return
        
        # CPU throttling: Rate limit message processing
        async with _message_limiter:
            now = asyncio.get_event_loop().time()
            if now - _last_message_time < _min_message_interval:
                await asyncio.sleep(_min_message_interval - (now - _last_message_time))
            _last_message_time = asyncio.get_event_loop().time()

            # Track messages sent in the server (not DMs)
            if message.guild is not None:
                track_message(message.author.id)

            # Protect the special name: Use cooldown to reduce CPU (only check once per 2 seconds per user)
            user_id = message.author.id
            import time
            current_time = time.time()
            last_check = _keyword_cooldowns.get(user_id, 0)
            
            # Only check keywords once per user every 2 seconds - HUGE CPU reduction
            if current_time - last_check >= _keyword_check_cooldown and message.content:
                _keyword_cooldowns[user_id] = current_time
                
                content = message.content.lower()
                keywords = ("vrotex", "vr0", "vr0tex", "vortex")
                if any(k in content for k in keywords):
                    guild = message.guild
                    print(f"DEBUG: Keyword detected in message from {message.author}: {message.content}")

                    # Delete the message
                    try:
                        await message.delete()
                        print(f"DEBUG: Message deleted successfully")
                    except Exception as e:
                        print(f"DEBUG: Failed to delete message: {e}")
                    
                    # Send the response
                    try:
                        embed = V2Embed(
                            title="👑 FORBIDDEN WORD 👑",
                            description=f"A mere peasant cannot utter that precious name!",
                            color=discord.Color.gold()
                        )
                        embed.add_field(
                            name="⚡ DECREE FROM THE HEAVENS ⚡",
                            value="Our king, **Vr0tex**, is the GOD.\n\nOnly those worthy may speak his divine name.",
                            inline=False
                        )
                        embed.set_footer(text="~ Vr0tex's Divine Guard ~")
                        msg = await message.channel.send(f"{message.author.mention}", embed=embed, delete_after=8)
                        print(f"DEBUG: Response sent successfully: {msg.id}")
                    except Exception as e:
                        print(f"DEBUG: Failed to send response: {e}")
                        import traceback
                        traceback.print_exc()

        await self.process_commands(message)


    async def on_command_error(self, ctx, error):
        print(f"DEBUG: Command '{ctx.command}' failed: {error}")
        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore commands that don't exist
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(f"❌ You don't have permission to use this command!", delete_after=5)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: `{error.param.name}`", delete_after=5)
        else:
            print(f"DEBUG: Command Error: {error}")

    async def on_command(self, ctx):
        print(f"DEBUG: Command '{ctx.command}' invoked by {ctx.author}")

    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """Update the online helpers list when a member's presence changes."""
        global ONLINE_HELPERS_MESSAGE_ID, ONLINE_HELPERS_CHANNEL_ID
        
        # Only process if the member has a helper role
        has_helper_role = any(role.id in GAME_HELPER_ROLES.values() for role in after.roles)
        if not has_helper_role:
            return
        
        # Check if status changed between online and offline
        before_online = before.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)
        after_online = after.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)
        
        if before_online == after_online:
            return  # Status didn't change between online/offline
        
        # Try to update the online helpers message if it exists
        if ONLINE_HELPERS_MESSAGE_ID and ONLINE_HELPERS_CHANNEL_ID:
            try:
                guild = after.guild
                channel = guild.get_channel(ONLINE_HELPERS_CHANNEL_ID)
                if channel:
                    message = await channel.fetch_message(ONLINE_HELPERS_MESSAGE_ID)
                    embed = await create_online_helpers_embed(guild)
                    await message.edit(embed=embed)
                    helper_name = next((game for game, role_id in GAME_HELPER_ROLES.items() if role_id in [r.id for r in after.roles]), "Unknown")
                    status = "online" if after_online else "offline"
                    print(f"✅ Updated online helpers list: {after.name} is now {status} ({helper_name})")
            except discord.NotFound:
                print("Online helpers message not found, need to recreate")
                ONLINE_HELPERS_MESSAGE_ID = None
                save_online_helpers_config()
            except Exception as e:
                print(f"Error updating online helpers: {e}")

bot = ParadoxBot()

@bot.command()
@commands.has_permissions(administrator=True)
async def welcome(ctx, setting: str = None, target_channel: discord.TextChannel = None):
    """Enable or disable the welcome message system for this guild."""
    guild_id = ctx.guild.id
    if setting is None:
        channel_id = get_welcome_channel_id_for_guild(guild_id)
        state = "enabled" if WELCOME_ENABLED.get(guild_id, False) else "disabled"
        await ctx.send(f"✅ Welcome system is currently **{state}** for this server.\nTarget channel: <#{channel_id}>")
        return

    value = setting.lower()
    if value in ("set", "channel"):
        if target_channel is None:
            await ctx.send("❌ Usage: `!welcome set #channel`")
            return
        WELCOME_CHANNELS[guild_id] = target_channel.id
        save_welcome_settings()
        await ctx.send(f"✅ Welcome channel set to {target_channel.mention}.")
        return

    if value in ("on", "enable", "enabled", "true"):
        WELCOME_ENABLED[guild_id] = True
        if guild_id not in WELCOME_CHANNELS:
            WELCOME_CHANNELS[guild_id] = WELCOME_CHANNEL_ID
        save_welcome_settings()
        await ctx.send(f"✅ Welcome system turned **on**. New joins will be posted in <#{get_welcome_channel_id_for_guild(guild_id)}>.")
    elif value in ("off", "disable", "disabled", "false"):
        WELCOME_ENABLED[guild_id] = False
        save_welcome_settings()
        await ctx.send(f"✅ Welcome system turned **off**. No welcome posts will be sent in <#{get_welcome_channel_id_for_guild(guild_id)}>.")
    else:
        await ctx.send("❌ Usage: `!welcome on`, `!welcome off`, or `!welcome set #channel`")

@bot.command()
@commands.has_permissions(administrator=True)
async def testwelcome(ctx):
    """Preview the welcome post in the configured welcome channel."""
    welcome_channel_id = get_welcome_channel_id_for_guild(ctx.guild.id)
    welcome_channel = ctx.guild.get_channel(welcome_channel_id)
    if not welcome_channel or not isinstance(welcome_channel, discord.TextChannel):
        await ctx.send(f"❌ Welcome channel <#{welcome_channel_id}> not found in this server.")
        return

    welcome_banner = (
        get_asset_path("welcome_banner.png")
        or get_asset_path("yuji.png")
        or get_asset_path("bot_avatar.png")
        or get_asset_path("paradox img.png")
        or get_asset_path("setup_header.png")
    )
    file = None
    if welcome_banner and os.path.exists(welcome_banner):
        file = discord.File(welcome_banner, filename="welcome_banner.png")

    embed = V2Embed(
        title="Welcome to Paradox Guild",
        description=(
            f"**Welcome, {ctx.author.mention}!**\n\n"
            "We’re glad you’re here.\n"
            "Take a moment to review the server rules and get familiar with the community."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="Server Guides",
        value="Check the rules, ticket channels, and helper applications in the server.\n\nIf you are interested in helping the community, visit the #helper-application channel and submit your application. A staff member will review it shortly after.",
        inline=False
    )
    if file:
        embed.set_image(url="attachment://welcome_banner.png")
        await welcome_channel.send(content=f"{ctx.author.mention} has joined the server!", file=file, embed=embed)
    else:
        await welcome_channel.send(content=f"{ctx.author.mention} has joined the server!", embed=embed)

    await ctx.send("✅ Welcome preview sent to the welcome channel.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    embed = V2Embed()
    file = None
    setup_header_path = get_asset_path("paradox img.png") or get_asset_path("setup_header.png")
    if os.path.exists(setup_header_path):
        file = discord.File(setup_header_path, filename="header.png")
        embed.set_image(url="attachment://header.png")
    
    embed.description = (
        f"**@everyone**\n\n"
        f"**{Emojis.CARRY} [ PARADOX CARRY REQUESTS ]**\n\n"
        f"**| {Emojis.INFO} Information**\n"
        f"**| Welcome to the Elite Carry Service!**\n"
        f"**| Your place for fast and professional carries.**\n\n"
        f"**| {Emojis.GAME} Supported Games**\n"
        f"```diff\n"
        f"+ Anime Last Stand (ALS)\n"
        f"+ Anime Vanguards (AV)\n"
        f"+ Universal Tower Defense (UTD)\n"
        f"+ Anime Expeditions (AE)\n"
        f"+ and many more soon...\n"
        f"```\n"
        f"**| {Emojis.ARROW} How to start?**\n"
        f"**| Select your game from the menu below!**\n\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )
    embed.set_footer(text="Paradox System • Premium Edition", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    
    await ctx.send(file=file if file else None, embed=embed, view=ParadoxTicketView())

@bot.command()
@commands.has_permissions(administrator=True)
async def helper_setup(ctx):
    embed = V2Embed()
    file = None
    setup_header_path = get_asset_path("paradox img.png") or get_asset_path("setup_header.png")
    if os.path.exists(setup_header_path):
        file = discord.File(setup_header_path, filename="header.png")
        embed.set_image(url="attachment://header.png")
    
    embed.description = (
        f"**@everyone**\n\n"
        f"**{Emojis.STAFF} [ HELPER APPLICATIONS ]**\n\n"
        f"**| {Emojis.INFO} Information**\n"
        f"**| Interested in joining our Elite Staff?**\n"
        f"**| We are looking for professional carriers!**\n\n"
        f"**| {Emojis.ARROW} How to apply?**\n"
        f"**| Select your main game below and answer the**\n"
        f"**| questions in the modal that appears.**\n\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )
    embed.set_footer(text="Paradox System • Premium Edition", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    
    await ctx.send(file=file if file else None, embed=embed, view=HelperApplicationView())

@bot.command()
async def online_helpers(ctx):
    """Set up the online helpers list in the designated channel."""
    global ONLINE_HELPERS_MESSAGE_ID, ONLINE_HELPERS_CHANNEL_ID
    try:
        # Get the designated channel
        channel = bot.get_channel(ONLINE_HELPERS_CHANNEL_ID)
        if not channel:
            await ctx.send(f"❌ Could not find the designated helpers channel (ID: {ONLINE_HELPERS_CHANNEL_ID})")
            return
        
        # Create the embed
        embed = await create_online_helpers_embed(ctx.guild)
        
        # Post or update the message
        if ONLINE_HELPERS_MESSAGE_ID:
            try:
                message = await channel.fetch_message(ONLINE_HELPERS_MESSAGE_ID)
                await message.edit(embed=embed)
                await ctx.send(f"✅ Online helpers list updated in {channel.mention}")
            except discord.NotFound:
                # Message was deleted, create a new one
                message = await channel.send(embed=embed)
                ONLINE_HELPERS_MESSAGE_ID = message.id
                save_online_helpers_config()
                await ctx.send(f"✅ Online helpers list created in {channel.mention}")
        else:
            # First time setup
            message = await channel.send(embed=embed)
            ONLINE_HELPERS_MESSAGE_ID = message.id
            save_online_helpers_config()
            await ctx.send(f"✅ Online helpers list posted to {channel.mention}")
        
        print(f"✅ Online helpers list setup: Message ID {ONLINE_HELPERS_MESSAGE_ID} in channel {ONLINE_HELPERS_CHANNEL_ID}")
    except Exception as e:
        await ctx.send(f"❌ Error setting up online helpers: {e}")
        print(f"Error in online_helpers command: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def helpers_channel(ctx, channel: discord.TextChannel = None):
    """Set the channel where the online helpers list will be displayed."""
    global ONLINE_HELPERS_CHANNEL_ID, ONLINE_HELPERS_MESSAGE_ID
    
    if channel is None:
        channel = ctx.channel
    
    try:
        ONLINE_HELPERS_CHANNEL_ID = channel.id
        ONLINE_HELPERS_MESSAGE_ID = None  # Reset message ID to create a new one
        save_online_helpers_config()
        
        await ctx.send(f"✅ Online helpers channel set to {channel.mention}")
        print(f"✅ Helpers channel changed to {channel.id}")
    except Exception as e:
        await ctx.send(f"❌ Error setting helpers channel: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def verify_helpers(ctx):
    """Verify and display which users have helper roles and their online status, then update the helpers list."""
    global ONLINE_HELPERS_MESSAGE_ID, ONLINE_HELPERS_CHANNEL_ID
    guild = ctx.guild
    
    embed = V2Embed(
        title="🔍 Helper Role Verification",
        description="Checking all helper roles in the server...",
        color=discord.Color.blue()
    )
    
    for game, role_id in GAME_HELPER_ROLES.items():
        role = guild.get_role(role_id)
        
        if role is None:
            embed.add_field(
                name=f"❌ {game}",
                value=f"Role ID {role_id} not found in this server!",
                inline=False
            )
        else:
            # Get members with this role
            members_with_role = [m for m in role.members if not m.bot]
            online_members = [m for m in members_with_role if m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)]
            
            if online_members:
                online_list = ", ".join([f"{m.name}" for m in online_members])
                embed.add_field(
                    name=f"✅ {game} - {role.name}",
                    value=f"**Total members:** {len(members_with_role)}\n**Online:** {len(online_members)}\n{online_list}",
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"✅ {game} - {role.name}",
                    value=f"**Total members:** {len(members_with_role)}\n**Online:** 0\nNo one online",
                    inline=False
                )
    
    await ctx.send(embed=embed)
    
    # Now update the online helpers list
    try:
        if ONLINE_HELPERS_MESSAGE_ID and ONLINE_HELPERS_CHANNEL_ID:
            channel = bot.get_channel(ONLINE_HELPERS_CHANNEL_ID)
            if channel:
                try:
                    message = await channel.fetch_message(ONLINE_HELPERS_MESSAGE_ID)
                    helpers_embed = await create_online_helpers_embed(guild)
                    await message.edit(embed=helpers_embed)
                    await ctx.send("✅ Online helpers list has been updated!")
                    print(f"✅ Online helpers list refreshed via verify_helpers")
                except discord.NotFound:
                    await ctx.send("⚠️ Online helpers message not found. Run `!online_helpers` to create it.")
                    ONLINE_HELPERS_MESSAGE_ID = None
                    save_online_helpers_config()
                except Exception as e:
                    await ctx.send(f"⚠️ Could not update helpers list: {e}")
                    print(f"Error updating helpers list: {e}")
        else:
            await ctx.send("⚠️ Online helpers list not set up yet. Run `!online_helpers` first.")
    except Exception as e:
        print(f"Error in verify_helpers update: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def lockdown(ctx, channel: discord.TextChannel = None):
    """Lock a channel so only admins, mods, Coowner, vr0tex, and moderator roles can type."""
    if channel is None:
        channel = ctx.channel

    guild = ctx.guild
    if channel.guild != guild:
        await ctx.send("❌ That channel is not in this server.")
        return

    access_roles = []
    for role_name in ["Admin", "Mods", "Coowner", "vr0tex"]:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            access_roles.append(role)

    for role in guild.roles:
        if "moderator" in role.name.lower() and role not in access_roles:
            access_roles.append(role)

    try:
        await channel.set_permissions(guild.default_role, send_messages=False)

        community_role = discord.utils.get(guild.roles, name="community members")
        if community_role:
            await channel.set_permissions(community_role, send_messages=False)

        for role in access_roles:
            await channel.set_permissions(role, send_messages=True)

        role_names = ", ".join([role.name for role in access_roles]) or "admins and mods"
        embed = V2Embed(
            title="🔒 Channel Locked",
            description=f"{channel.mention} has been locked down.\n\n**Access granted to:** {role_names}",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to modify channel permissions. Make sure my role is above the roles I need to manage.")
    except Exception as e:
        await ctx.send(f"❌ Error locking channel: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    """Unlock a channel previously locked by !lockdown (restore send_messages to everyone)."""
    if channel is None:
        channel = ctx.channel

    guild = ctx.guild
    if channel.guild != guild:
        await ctx.send("❌ That channel is not in this server.")
        return

    try:
        # Allow everyone to send messages again by clearing the overwrite for @everyone
        await channel.set_permissions(guild.default_role, overwrite=None)

        # Also clear community members overwrite if present
        community_role = discord.utils.get(guild.roles, name="community members")
        if community_role:
            await channel.set_permissions(community_role, overwrite=None)

        embed = V2Embed(
            title="🔓 Channel Unlocked",
            description=f"{channel.mention} has been unlocked for everyone.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to modify channel permissions. Make sure my role is above the roles I need to manage.")
    except Exception as e:
        await ctx.send(f"❌ Error unlocking channel: {e}")


@bot.command()
async def vouch(ctx, target: discord.Member, game: str, *, feedback: str = "Fast, safe, and professional!"):
    if target.id == ctx.author.id:
        await ctx.send("❌ You can't vouch for yourself!")
        return

    previous_total = get_total_vouches(target.id)
    local_record_id = save_vouch_record(
        booster_id=target.id,
        customer_id=ctx.author.id,
        game=game,
        feedback=feedback,
        star_rating=5,
        ticket_id=ctx.channel.id,
        booster_name=target.name,
        source='local',
    )

    db_success = False
    if supabase:
        try:
            supabase.table("vouches").insert({
                "booster_id": str(target.id),
                "customer_id": str(ctx.author.id),
                "game": game,
                "booster_name": target.name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "feedback": feedback,
                "star_rating": 5,
                "ticket_id": str(ctx.channel.id),
            }).execute()
            db_success = True
        except Exception as e:
            print(f"Vouch error (Supabase down, using local vouches): {e}")

    total_vouches = get_total_vouches(target.id, previous_total + 1)
    embed = create_vouch_embed(ctx.author, target, game, feedback, total_vouches, ctx.channel.id)
    if supabase and db_success:
        await ctx.send(embed=embed)
    else:
        await ctx.send(content="⚠️ Database not connected or offline (Local vouch saved securely)", embed=embed)

@bot.command()
async def myvouches(ctx):
    bonus = get_bonus_vouches(ctx.author.id)
    total_vouches = bonus["total"]
    main_game = max(bonus["games"], key=bonus["games"].get) if bonus["games"] else "Unknown"
    latest_vouch = None

    try:
        conn = sqlite3.connect(VOUCH_DB_PATH)
        local_rows = conn.execute(
            "SELECT booster_id, customer_id, game, feedback, star_rating, ticket_id, booster_name, created_at FROM vouch_records WHERE booster_id = ? ORDER BY id DESC",
            (str(ctx.author.id),),
        ).fetchall()
        conn.close()
        if local_rows:
            latest_vouch = {
                "booster_id": local_rows[0][0],
                "customer_id": local_rows[0][1],
                "game": local_rows[0][2],
                "feedback": local_rows[0][3],
                "star_rating": local_rows[0][4],
                "ticket_id": local_rows[0][5],
                "booster_name": local_rows[0][6],
                "created_at": local_rows[0][7],
            }
            total_vouches += len(local_rows)
            main_game = latest_vouch.get("game", main_game)
    except Exception as e:
        print(f"Myvouches local DB error: {e}")

    if supabase:
        try:
            result = supabase.table("vouches").select("*").eq(
                "booster_id", str(ctx.author.id)
            ).order("id", desc=True).execute()
            vouch_list = result.data or []
            total_vouches += len(vouch_list)
            if not latest_vouch and vouch_list:
                latest_vouch = vouch_list[0]
                main_game = latest_vouch.get("game", main_game)
        except Exception as e:
            print(f"Myvouches error (Supabase unavailable): {e}")

    if total_vouches == 0:
        await ctx.send(f"**{ctx.author.name}** hasn't earned any vouches yet!")
        return

    if latest_vouch:
        customer_id = int(latest_vouch.get("customer_id", 0))
        customer = ctx.guild.get_member(customer_id) if ctx.guild else None
        if customer is None and customer_id:
            try:
                customer = await bot.fetch_user(customer_id)
            except discord.HTTPException:
                customer = None

        if customer is not None:
            embed = create_vouch_embed(
                customer,
                ctx.author,
                latest_vouch.get("game", "Unknown"),
                latest_vouch.get("feedback", "Vouch recorded successfully!"),
                total_vouches,
                latest_vouch.get("ticket_id", ctx.channel.id),
                star_rating=int(latest_vouch.get("star_rating", 5)),
            )
            await ctx.send(embed=embed)
            return

    embed = create_vouch_embed(
        ctx.author,
        ctx.author,
        main_game,
        latest_vouch.get("feedback", "Vouch total") if latest_vouch else "Vouch total",
        total_vouches,
        latest_vouch.get("ticket_id", ctx.channel.id) if latest_vouch else ctx.channel.id,
        star_rating=int(latest_vouch.get("star_rating", 5)) if latest_vouch else 5,
        include_details=False,
    )
    await ctx.send(embed=embed)

@bot.command(name="leaderboard", aliases=["vouchlb", "topvouches"])
async def vouch_leaderboard(ctx):
    """Show the members with the most lifetime vouches."""
    totals = {}
    names = {}
    database_available = False

    try:
        conn = sqlite3.connect(VOUCH_DB_PATH)
        for user_id, total, games_json in conn.execute("SELECT user_id, total, games_json FROM bonus_vouches"):
            totals[str(user_id)] = int(total)
            if isinstance(json.loads(games_json or "{}"), dict):
                names[str(user_id)] = names.get(str(user_id), "Local User")
        for user_id, game, booster_name in conn.execute("SELECT booster_id, game, booster_name FROM vouch_records"):
            key = str(user_id)
            totals[key] = totals.get(key, 0) + 1
            if booster_name:
                names[key] = booster_name
        conn.close()
        database_available = True
    except Exception as exc:
        print(f"Leaderboard local DB error: {exc}")
        try:
            with open(os.path.join(BASE_DIR, "bonus_vouches.json"), "r") as f:
                bonus_data = json.load(f)
            for user_id, user_data in bonus_data.items():
                totals[user_id] = user_data.get("total", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if supabase:
        try:
            result = supabase.table("vouches").select("booster_id, booster_name").execute()
            for vouch in result.data or []:
                user_id = str(vouch.get("booster_id", ""))
                if not user_id:
                    continue
                totals[user_id] = totals.get(user_id, 0) + 1
                if vouch.get("booster_name"):
                    names[user_id] = vouch["booster_name"]
            database_available = True
        except Exception as e:
            print(f"Leaderboard error (Supabase unavailable): {e}")

    ranked = sorted(
        ((user_id, total) for user_id, total in totals.items() if total > 0),
        key=lambda entry: (-entry[1], entry[0]),
    )[:10]
    if not ranked:
        await ctx.send("No vouches have been recorded yet!")
        return

    medal_emojis = ["🥇", "🥈", "🥉"]
    lines = []
    for position, (user_id, total) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(user_id)) if ctx.guild else None
        display_name = member.mention if member else names.get(user_id, f"User {user_id}")
        marker = medal_emojis[position - 1] if position <= len(medal_emojis) else f"`#{position}`"
        lines.append(f"{marker} {display_name} **{total:,}** vouches")

    embed = discord.Embed(
        title="🏆 Vouch Leaderboard",
        description="\n".join(lines),
        color=0xF4D03F,
    )
    embed.set_footer(text="Lifetime vouches • Top 10")
    if not database_available:
        embed.set_footer(text="Local bonus vouches only • Top 10")
    await ctx.send(embed=embed)

@bot.command(aliases=["givevouches"])
@commands.has_permissions(administrator=True)
async def givevouch(ctx, target: discord.Member, amount: int, game: str = "ALS"):
    if amount <= 0:
        await ctx.send("❌ Amount must be greater than 0.")
        return
        
    try:
        # Add to local bonus file
        add_bonus_vouches(target.id, amount, game)
        
        total_vouches = get_total_vouches(target.id)
            
        embed = create_vouch_embed(
            ctx.author, target, game, "Bonus Vouches Granted!", total_vouches, ctx.channel.id
        )
        await ctx.send(f"✅ Successfully gave {amount:,} bonus vouches to {target.mention}!", embed=embed)
    except Exception as e:
        print(f"Givevouch error: {e}")
        await ctx.send(f"❌ Error adding bonus vouches: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def removevouches(ctx, target: discord.Member, amount: int, game: str = "ALS"):
    if amount <= 0:
        await ctx.send("❌ Amount must be greater than 0.")
        return
        
    try:
        # Subtract from local bonus file
        add_bonus_vouches(target.id, -amount, game)
        _vouch_total_cache.pop(str(target.id), None)
        
        total_vouches = get_total_vouches(target.id)
            
        embed = create_vouch_embed(
            ctx.author, target, game, f"Removed {amount} vouches.", total_vouches, ctx.channel.id
        )
        await ctx.send(f"✅ Successfully removed {amount:,} vouches from {target.mention}!", embed=embed)
    except Exception as e:
        print(f"Removevouches error: {e}")
        await ctx.send(f"❌ Error removing vouches: {e}")

@bot.command()
async def profile(ctx, target: discord.Member = None):
    target = target or ctx.author
    total_vouches = 0
    game_count = {}
    
    # Add bonus vouches first
    bonus = get_bonus_vouches(target.id)
    total_vouches += bonus["total"]
    for g, count in bonus["games"].items():
        game_count[g] = game_count.get(g, 0) + count

    if supabase:
        try:
            res = supabase.table("vouches").select("*").eq("booster_id", str(target.id)).execute()
            vouch_list = res.data
            total_vouches += len(vouch_list)
            for vouch in vouch_list:
                g = vouch["game"]
                game_count[g] = game_count.get(g, 0) + 1
        except Exception as e:
            print(f"Profile error (Supabase down, fallback to local): {e}")

    if total_vouches == 0:
        await ctx.send(f"**{target.name}** hasn't earned any vouches yet!")
        return
    
    async with ctx.typing():
        img_data = await create_profile_card(target.name, total_vouches, game_count, target.display_avatar.url)
        file = discord.File(img_data, filename="profile.png")
        await ctx.send(file=file)

@bot.command()
@commands.has_permissions(administrator=True)
async def sync(ctx):
    """Refreshes the emoji cache"""
    Emojis.update(bot)
    await ctx.send("✅ Emojis have been refreshed from cache!")

@bot.command(name="help")
async def custom_help(ctx, *args):
    """Show this help menu."""
    if len(args) >= 2 and args[0].lower() == "paradox" and args[1] == "2":
        fallback_descriptions = {
            "myvouches": "View your personal vouch card.",
            "leaderboard": "Show the members with the most vouches.",
            "profile": "View yours or another user's profile card.",
            "vouch": "Vouch for a booster after a run.",
            "setup": "Deploy the Carry Request ticket system.",
            "helper_setup": "Deploy the Staff Application system.",
            "givevouch": "Grant bonus vouches to a staff member.",
            "removevouches": "Deduct vouches from a staff member.",
            "sync": "Force refresh the emoji cache and bot settings.",
            "help": "Show this help menu.",
            "ping_setup": "Deploy the ping role selection embed.",
            "invites": "Show invite stats for a user.",
            "role": "Mass-assign and auto-assign roles.",
            "role add": "Configure role mass assignment.",
            "changelog": "Post a new bot changelog/update.",
            "changelog major": "Post a major changelog with a ping.",
            "changelog minor": "Post a minor changelog without a ping.",
            "shutdown": "Shut down the bot gracefully.",
            "online": "Post a bot online message.",
            "botchanges": "Post a bot updates/changes message."
        }

        # Ensure custom commands are described
        fallback_descriptions.setdefault("warn", "Warn a user and record the warning.")
        fallback_descriptions.setdefault("removewarn", "Remove one or more warnings from a user.")

        user_cmds = []
        admin_cmds = []
        
        for cmd in bot.commands:
            if cmd.hidden:
                continue
                
            # Determine if command is staff/admin command
            is_admin = False
            for check in cmd.checks:
                check_name = getattr(check, "__qualname__", "")
                if "has_permissions" in check_name or "has_any_role" in check_name or "has_role" in check_name:
                    is_admin = True
                    break
            
            if isinstance(cmd, commands.Group):
                for subcmd in cmd.commands:
                    sub_sig = subcmd.signature
                    usage = f"`!{cmd.name} {subcmd.name} {sub_sig}`".strip()
                    sub_desc = subcmd.help
                    if not sub_desc:
                        sub_desc = fallback_descriptions.get(f"{cmd.name} {subcmd.name}", "No description provided.")
                    else:
                        sub_desc = sub_desc.split("\n")[0]
                    
                    cmd_info = f"> {usage} - {sub_desc}"
                    if is_admin:
                        admin_cmds.append(cmd_info)
                    else:
                        user_cmds.append(cmd_info)
            else:
                sig = cmd.signature
                usage = f"`!{cmd.name} {sig}`".strip()
                desc = cmd.help
                if not desc:
                    desc = fallback_descriptions.get(cmd.name, "No description provided.")
                else:
                    desc = desc.split("\n")[0]
                    
                cmd_info = f"> {usage} - {desc}"
                if is_admin:
                    admin_cmds.append(cmd_info)
                else:
                    user_cmds.append(cmd_info)
                    
        user_cmds.sort()
        admin_cmds.sort()
        
        user_cmds_str = "\n".join(user_cmds)
        admin_cmds_str = "\n".join(admin_cmds)
        
        embed = V2Embed(
            title=f"{Emojis.INFO} Paradox Bot v2.0 - Command List",
            description=(
                "Welcome to the Paradox Command Guide! Here are the available commands for your server.\n\n"
                f"**{Emojis.ARROW} User Commands**\n"
                f"{user_cmds_str}\n\n"
                f"**{Emojis.ARROW} Staff & Admin Commands**\n"
                f"{admin_cmds_str}"
            )
        )
        embed.set_footer(text="Paradox System • Premium Edition", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❓ Use `!twinski please do it` to see the full list of bot commands.")


@bot.command(name="twinski")
async def twinski(ctx, *args):
    """Alias to show the Paradox v2 command list. Accepts extra words like 'please do it'."""
    await custom_help(ctx, "paradox", "2")

@bot.command(name="ping_setup")
@commands.has_permissions(administrator=True)
async def ping_setup(ctx):
    """Deploy the ping role selection embed."""
    embed = V2Embed(
        title="🔔 Notification Pings",
        description=(
            f"**| {Emojis.INFO} Stay in the loop!**\n"
            "**| Click a button below to toggle your ping roles.**\n"
            "**| Click again at any time to remove it.**\n\n"
            "📢 **Announcement Pings** — Server news & important updates\n"
            "🎉 **Giveaway Pings** — Get notified when giveaways go live\n"
            "🎊 **Event Pings** — Be the first to know about events\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
        )
    )
    embed.set_footer(text="Paradox System • Ping Roles", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_thumbnail(url=ctx.guild.me.display_avatar.url)
    await ctx.send(embed=embed, view=PingRoleView())
    await ctx.message.delete()
@bot.command(name="invites")
async def invites_cmd(ctx, user: discord.Member = None):
    """Show invite stats for a user."""
    target = user or ctx.author

    # Get live invite data from Discord for accurate historical counts
    live_total = 0
    try:
        guild_invites = await ctx.guild.invites()
        for inv in guild_invites:
            if inv.inviter and inv.inviter.id == target.id:
                live_total += inv.uses
    except Exception:
        pass

    # Get runtime tracked data (joins/leaves since bot started)
    data = bot.invite_tracker.get(str(target.id), {"joined": [], "left": [], "historical": 0})
    live_joins = len(data["joined"])   # joins tracked since bot start
    left = len(data["left"])           # leaves tracked since bot start

    # Use the higher of live Discord count vs runtime tracked count
    total_joined = max(live_total, live_joins)
    still_here = total_joined - left

    embed = V2Embed(
        title=f"{Emojis.INFO} Invite Stats",
        description=f"Invite statistics for {target.mention}"
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="✅ Total Invited", value=f"```\n{total_joined}\n```", inline=True)
    embed.add_field(name="🚪 Left Server", value=f"```\n{left}\n```", inline=True)
    embed.add_field(name="👥 Still Here", value=f"```\n{still_here}\n```", inline=True)
    embed.set_footer(text="Paradox System • Invite Tracker")
    await ctx.send(embed=embed)

@invites_cmd.error
async def invites_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("❌ Could not find that user. Please mention a valid member.", delete_after=5)

@bot.group(name="role", aliases=["roles"], invoke_without_command=True)
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def role(ctx):
    await ctx.send("Usage: `!role add`")

@role.command(name="add")
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def role_add(ctx):
    await ctx.send("Please reply with the Role ID you want to mass-assign and auto-assign (or type `cancel` to abort).")
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        msg = await bot.wait_for('message', check=check, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send("❌ Timed out waiting for Role ID.")
        return

    if msg.content.lower() == 'cancel':
        await ctx.send("Cancelled.")
        return
        
    try:
        role_id = int(msg.content.strip())
    except ValueError:
        await ctx.send("❌ Invalid Role ID. Must be a number.")
        return
        
    role = ctx.guild.get_role(role_id)
    if not role:
        await ctx.send(f"❌ Role with ID `{role_id}` not found in this server!")
        return

    view = discord.ui.View(timeout=60)
    
    async def both_callback(interaction):
        if interaction.user != ctx.author: return
        await interaction.response.edit_message(content=f"✅ Saved `{role.name}`. Starting mass assignment to **current members**...", view=None)
        view.stop()
        
        add_auto_role(role_id)
        
        success = 0
        failed = 0
        async def assign_roles():
            nonlocal success, failed
            for member in ctx.guild.members:
                if role not in member.roles and not member.bot:
                    try:
                        await member.add_roles(role)
                        success += 1
                        await asyncio.sleep(0.5) 
                    except Exception:
                        failed += 1
            await ctx.send(f"✅ Mass assignment for `{role.name}` complete!\nAdded to: **{success}** members.\nFailed: **{failed}** members.")
        bot.loop.create_task(assign_roles())

    async def future_only_callback(interaction):
        if interaction.user != ctx.author: return
        await interaction.response.edit_message(content=f"✅ Added `{role.name}` to auto-roles for **future members only**.", view=None)
        view.stop()
        add_auto_role(role_id)

    async def current_only_callback(interaction):
        if interaction.user != ctx.author: return
        await interaction.response.edit_message(content=f"✅ Starting mass assignment for `{role.name}` to **current members only** (will not be given to future members)...", view=None)
        view.stop()
        
        success = 0
        failed = 0
        async def assign_roles():
            nonlocal success, failed
            for member in ctx.guild.members:
                if role not in member.roles and not member.bot:
                    try:
                        await member.add_roles(role)
                        success += 1
                        await asyncio.sleep(0.5) 
                    except Exception:
                        failed += 1
            await ctx.send(f"✅ Mass assignment for `{role.name}` complete!\nAdded to: **{success}** members.\nFailed: **{failed}** members.")
        bot.loop.create_task(assign_roles())

    btn_both = discord.ui.Button(label="Everyone + Future Members", style=discord.ButtonStyle.green)
    btn_both.callback = both_callback
    
    btn_future = discord.ui.Button(label="Future Members Only", style=discord.ButtonStyle.blurple)
    btn_future.callback = future_only_callback
    
    btn_current = discord.ui.Button(label="Current Members Only", style=discord.ButtonStyle.gray)
    btn_current.callback = current_only_callback
    
    view.add_item(btn_both)
    view.add_item(btn_future)
    view.add_item(btn_current)
    
    await ctx.send(f"Who should receive the `{role.name}` role?", view=view)

@bot.group(invoke_without_command=True)
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def changelog(ctx):
    await ctx.send("Usage:\n`!changelog major <message>` - Posts update and pings @bot changes\n`!changelog minor <message>` - Posts update without pinging")

async def send_changelog(ctx, message: str, is_major: bool):
    channel_id = 1504584461151375461
    channel = bot.get_channel(channel_id)
    if not channel:
        await ctx.send(f"❌ Could not find changelog channel ({channel_id}).")
        return

    embed = V2Embed(
        title="🛠️ Bot Update & Changes",
        description=message,
        color=discord.Color.brand_green() if is_major else discord.Color.blurple()
    )
    embed.set_footer(text=f"Update pushed by {ctx.author.name}", icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None)

    content = "<@&1500218240637341808>" if is_major else None
    await channel.send(content=content, embed=embed)
    await ctx.send("✅ Changelog posted successfully!")

@changelog.command(name="major")
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def changelog_major(ctx, *, message: str):
    """Post a major changelog with a ping."""
    await send_changelog(ctx, message, is_major=True)

@changelog.command(name="minor")
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def changelog_minor(ctx, *, message: str):
    """Post a minor changelog without a ping."""
    await send_changelog(ctx, message, is_major=False)


@bot.command()
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def shutdown(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    await ctx.send("🛑 Shutting down gracefully...", delete_after=3)
    await bot.close()

@bot.command()
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def online(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    
    try:
        channel = bot.get_channel(1504584461151375461) or await bot.fetch_channel(1504584461151375461)
        if channel:
            embed = V2Embed(
                title="🚀 Bot Online",
                description="The bot is now online and ready to assist! Thank you for your patience.",
                color=discord.Color.brand_green()
            )
            await channel.send(embed=embed)
            await ctx.send("✅ Online message sent!", delete_after=3)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}", delete_after=5)

@bot.command()
@commands.has_any_role(1500179848650555432, 1500183475070963762)
async def botchanges(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    
    try:
        channel = bot.get_channel(1504584461151375461) or await bot.fetch_channel(1504584461151375461)
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
            await ctx.send("✅ Bot changes message sent!", delete_after=3)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}", delete_after=5)

# ──────────────────────────────────────────
# USER LOOKUP SYSTEM (!searchup)
# ──────────────────────────────────────────

def is_lookup_allowed():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        allowed_roles = {"coowner", "vr0tex the goat", "moderator", "senior moderator", "head moderator", "admin", "administrator"}
        for role in ctx.author.roles:
            if role.name.lower() in allowed_roles:
                return True
        raise commands.MissingPermissions(["Lookup role requirement not met."])
    return commands.check(predicate)


def is_admin_or_moderator():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        # allow roles that include the word 'moderator'
        for role in ctx.author.roles:
            if 'moderator' in role.name.lower():
                return True
        raise commands.MissingPermissions(['Administrator or Moderator required.'])
    return commands.check(predicate)

class BanModal(discord.ui.Modal, title="Ban Member"):
    reason = discord.ui.TextInput(
        label="Reason for Ban",
        style=discord.TextStyle.paragraph,
        placeholder="Breaking server rules...",
        required=True,
        max_length=150
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        # Allow either the guild permission or one of the trusted moderator roles
        allowed_roles = {"coowner", "vr0tex the goat", "moderator", "senior moderator", "head moderator", "admin", "administrator"}
        has_role = any(role.name.lower() in allowed_roles for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.ban_members or has_role):
            await interaction.response.send_message("❌ You do not have permission to ban members.", ephemeral=True)
            return

        try:
            await self.member.ban(reason=f"Banned by {interaction.user.name}: {self.reason.value}")
            await interaction.response.send_message(f"✅ Successfully banned **{self.member.name}**.\nReason: {self.reason.value}", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to ban member: {e}", ephemeral=True)

class KickModal(discord.ui.Modal, title="Kick Member"):
    reason = discord.ui.TextInput(
        label="Reason for Kick",
        style=discord.TextStyle.paragraph,
        placeholder="Breaking server rules...",
        required=True,
        max_length=150
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        # Allow either the guild permission or one of the trusted moderator roles
        allowed_roles = {"coowner", "vr0tex the goat", "moderator", "senior moderator", "head moderator", "admin", "administrator"}
        has_role = any(role.name.lower() in allowed_roles for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.kick_members or has_role):
            await interaction.response.send_message("❌ You do not have permission to kick members.", ephemeral=True)
            return

        try:
            await self.member.kick(reason=f"Kicked by {interaction.user.name}: {self.reason.value}")
            await interaction.response.send_message(f"✅ Successfully kicked **{self.member.name}**.\nReason: {self.reason.value}", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to kick member: {e}", ephemeral=True)

class TimeoutModal(discord.ui.Modal, title="Timeout Member"):
    duration = discord.ui.TextInput(
        label="Duration (30m, 2h, 1d, 1h 30m, 2d 5h...)",
        placeholder="e.g. 1h 30m  or  2d  or  45m",
        required=True,
        max_length=30
    )
    reason = discord.ui.TextInput(
        label="Reason for Timeout",
        style=discord.TextStyle.paragraph,
        placeholder="Spamming, rule breaking...",
        required=True,
        max_length=150
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message(
                "❌ You do not have permission to timeout members.", ephemeral=True
            )
            return

        import re
        from datetime import timedelta

        raw = self.duration.value.lower().strip()
        # Support combined units: e.g. "1d 2h 30m", "1h30m", "90m", "7d"
        # Remove all spaces so "1h 30m" becomes "1h30m"
        condensed = raw.replace(" ", "")
        pattern = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$")
        m = pattern.fullmatch(condensed)

        if not m or not any(m.groups()):
            await interaction.response.send_message(
                "❌ **Invalid format!**\n"
                "Use combinations like:\n"
                "`30m` · `2h` · `1d` · `1h 30m` · `2d 5h` · `1d 2h 30m`",
                ephemeral=True
            )
            return

        days    = int(m.group(1)) if m.group(1) else 0
        hours   = int(m.group(2)) if m.group(2) else 0
        minutes = int(m.group(3)) if m.group(3) else 0

        td = timedelta(days=days, hours=hours, minutes=minutes)

        if td.total_seconds() <= 0:
            await interaction.response.send_message(
                "❌ Duration must be greater than 0.", ephemeral=True
            )
            return

        # Discord maximum timeout is 28 days
        max_td = timedelta(days=28)
        if td > max_td:
            await interaction.response.send_message(
                "❌ Discord's maximum timeout duration is **28 days**.", ephemeral=True
            )
            return

        # Build a human-readable summary
        parts = []
        if days:    parts.append(f"{days}d")
        if hours:   parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        duration_str = " ".join(parts)

        try:
            await self.member.timeout(
                td,
                reason=f"Timed out by {interaction.user.name}: {self.reason.value}"
            )
            await interaction.response.send_message(
                f"⏱️ **{self.member.display_name}** has been timed out for **{duration_str}**.\n"
                f"📝 Reason: {self.reason.value}",
                ephemeral=False
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to timeout member: {e}", ephemeral=True
            )


class WarnModal(discord.ui.Modal, title="Issue Warning"):
    reason = discord.ui.TextInput(
        label="Reason for Warning",
        style=discord.TextStyle.paragraph,
        placeholder="Explain why this warning is being issued (required)",
        required=True,
        max_length=250
    )

    def __init__(self, member: discord.Member, moderator: discord.Member):
        super().__init__()
        self.member = member
        self.moderator = moderator

    async def on_submit(self, interaction: discord.Interaction):
        # Permission check: reuse lookup allowed criteria
        allowed = interaction.user.guild_permissions.administrator or any(role.name.lower() in {"coowner", "vr0tex the goat", "moderator", "senior moderator", "head moderator", "admin", "administrator"} for role in interaction.user.roles)
        if not allowed:
            await interaction.response.send_message("❌ You do not have permission to warn members.", ephemeral=True)
            return

        reason_text = self.reason.value.strip()
        try:
            count = add_warning(self.member.id, self.moderator.id, reason_text)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add warning: {e}", ephemeral=True)
            return

        # Build embed for channel
        embed = V2Embed(
            title=f"{Emojis.STAFF} User Warned",
            description=f"**{self.member}** has been issued a warning.",
            color=discord.Color.orange()
        )
        embed.add_field(name="User", value=f"{self.member.mention} (`{self.member.id}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{self.moderator.mention}", inline=True)
        embed.add_field(name="Reason", value=f"{reason_text}", inline=False)
        embed.add_field(name="Total Warnings", value=f"{count}", inline=True)
        embed.set_footer(text=f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

        try:
            await interaction.channel.send(embed=embed)
        except Exception:
            pass

        # DM the user with a polite embed
        try:
            dm_embed = V2Embed(
                title="You have received a warning",
                description=f"You received a warning in **{interaction.guild.name}**.",
                color=discord.Color.orange()
            )
            dm_embed.add_field(name="Reason", value=reason_text, inline=False)
            dm_embed.add_field(name="Moderator", value=f"{self.moderator.name}", inline=True)
            dm_embed.add_field(name="Total Warnings", value=f"{count}", inline=True)
            await self.member.send(embed=dm_embed)
        except Exception:
            pass

        await interaction.response.send_message(f"✅ Warning issued to {self.member.mention}. Total warnings: {count}", ephemeral=True)


@bot.command(name="removewarn")
@is_lookup_allowed()
async def removewarn(ctx, member: discord.Member = None, num: int = 1):
    """Remove one or more warnings from a user."""
    if member is None:
        await ctx.send("❌ Usage: !removewarn @user [count]", delete_after=8)
        return

    if num <= 0:
        await ctx.send("❌ Count must be 1 or greater.", delete_after=8)
        return

    try:
        new_count, removed = remove_warning(member.id, num)
    except Exception as e:
        await ctx.send(f"❌ Failed to remove warnings: {e}", delete_after=8)
        return

    if not removed:
        await ctx.send(f"ℹ️ {member.mention} has no warnings to remove.", delete_after=8)
        return

    # Build embed summarizing removed warnings
    embed = V2Embed(
        title=f"{Emojis.STAFF} Warnings Removed",
        description=f"Removed {len(removed)} warning(s) from {member.mention}.",
        color=discord.Color.green()
    )
    embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name="Remaining Warnings", value=f"{new_count}", inline=True)

    # List removed entries (most recent first)
    lines = []
    for entry in reversed(removed):
        mod = f"<@{entry.get('moderator_id')}>" if entry.get('moderator_id') else 'Unknown'
        ts = entry.get('timestamp', '')
        reason = entry.get('reason', '') or 'No reason provided'
        lines.append(f"• {ts} — {reason} (by {mod})")

    embed.add_field(name="Removed Entries", value="\n".join(lines)[:1000], inline=False)
    embed.set_footer(text=f"Action by {ctx.author.name} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        await ctx.send(embed=embed)
    except Exception:
        await ctx.send(f"✅ Removed {len(removed)} warning(s). Remaining warnings: {new_count}")

    # Optionally DM the user about the removal
    try:
        dm = V2Embed(
            title="Warnings Updated",
            description=f"Some warnings on your record in **{ctx.guild.name}** were removed.",
            color=discord.Color.green()
        )
        dm.add_field(name="Removed", value=f"{len(removed)} warning(s)", inline=True)
        dm.add_field(name="Remaining Warnings", value=f"{new_count}", inline=True)
        await member.send(embed=dm)
    except Exception:
        pass

class UserLookupView(discord.ui.View):
    def __init__(self, member: discord.Member):
        # Non-persistent view (10 min timeout) with unique IDs per member+time
        uid = f"{member.id}_{int(datetime.now(timezone.utc).timestamp())}"
        super().__init__(timeout=600)
        self.member = member

        ban_btn = discord.ui.Button(
            label="Ban", style=discord.ButtonStyle.danger,
            custom_id=f"lu_ban_{uid}"
        )
        kick_btn = discord.ui.Button(
            label="Kick", style=discord.ButtonStyle.danger,
            custom_id=f"lu_kick_{uid}"
        )
        timeout_btn = discord.ui.Button(
            label="Timeout", style=discord.ButtonStyle.secondary,
            custom_id=f"lu_to_{uid}"
        )
        close_btn = discord.ui.Button(
            label="Close", style=discord.ButtonStyle.secondary,
            custom_id=f"lu_close_{uid}"
        )

        ban_btn.callback     = self.ban_callback
        kick_btn.callback    = self.kick_callback
        timeout_btn.callback = self.timeout_callback
        close_btn.callback   = self.close_callback

        self.add_item(ban_btn)
        self.add_item(kick_btn)
        self.add_item(timeout_btn)
        self.add_item(close_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        allowed_roles = {"coowner", "vr0tex the goat", "moderator", "senior moderator", "head moderator", "admin", "administrator"}
        for role in interaction.user.roles:
            if role.name.lower() in allowed_roles:
                return True
        await interaction.response.send_message(
            "❌ You do not have permission to use these moderation actions.", ephemeral=True
        )
        return False

    async def ban_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BanModal(self.member))

    async def kick_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(KickModal(self.member))

    async def timeout_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TimeoutModal(self.member))

    async def close_callback(self, interaction: discord.Interaction):
        await interaction.message.delete()


@bot.command(name="warn")
@is_admin_or_moderator()
async def warn(ctx, member: discord.Member = None):
    """Open a modal to issue a warning (admins & moderators only)."""
    if member is None:
        await ctx.send("❌ Usage: !warn @user", delete_after=8)
        return

    # Prevent warning the server owner or bot itself
    if member == ctx.guild.owner or member == ctx.guild.me:
        await ctx.send("❌ Cannot warn this user.", delete_after=8)
        return

    try:
        # Create a button that the moderator can click to open the modal (works from prefix commands)
        view = discord.ui.View(timeout=300)

        btn = discord.ui.Button(label="Provide Reason", style=discord.ButtonStyle.primary)
        async def btn_callback(interaction: discord.Interaction):
            # Only allow the moderator who invoked the command (or admins) to open the modal
            if interaction.user.id != ctx.author.id and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only the moderator who invoked this command can provide the reason.", ephemeral=True)
                return
            # Open the modal from the interaction (this is required for modals)
            modal = WarnModal(member, ctx.author)
            try:
                await interaction.response.send_modal(modal)
            except Exception:
                await interaction.response.send_message("❌ Failed to open modal. Please provide a reason using `!warn @user <reason>`.", ephemeral=True)

        btn.callback = btn_callback
        view.add_item(btn)

        # Add a cancel button to remove the prompt
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_cb(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only the moderator who invoked this command can cancel.", ephemeral=True)
                return
            await interaction.response.edit_message(content="Cancelled.", view=None)
        cancel.callback = cancel_cb
        view.add_item(cancel)

        await ctx.send(f"📝 {ctx.author.mention}, click the button below to provide a reason for warning {member.mention}.", view=view)
        return
    except Exception:
        await ctx.send("❗ Could not create prompt — please provide a reason inline: `!warn @user <reason>`", delete_after=8)
        return

    # Proceed to add warning with provided reason
    embed = V2Embed(
        title=f"{Emojis.STAFF} User Warned",
        description=f"**{member.mention}** has been issued a warning.",
        color=discord.Color.orange()
    )
    embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="Reason", value=f"{reason.strip()}", inline=False)
    embed.add_field(name="Total Warnings", value=f"{count}", inline=True)
    embed.set_footer(text=f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        await ctx.send(embed=embed)
    except Exception:
        await ctx.send(f"✅ {member.mention} has been warned. Total warnings: {count}")

    # DM the user
    try:
        dm_embed = V2Embed(
            title="You have received a warning",
            description=f"You received a warning in **{ctx.guild.name}**.",
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="Reason", value=reason.strip(), inline=False)
        dm_embed.add_field(name="Moderator", value=f"{ctx.author}", inline=True)
        dm_embed.add_field(name="Total Warnings", value=f"{count}", inline=True)
        await member.send(embed=dm_embed)
    except Exception:
        pass

@bot.command(name="searchup")
@is_lookup_allowed()
async def searchup(ctx, member: discord.Member = None):
    """Search up a user's server and account details."""
    member = member or ctx.author
    
    # 1. User Information
    username = member.name
    display_name = member.display_name
    discord_id = member.id
    is_bot = "Yes" if member.bot else "No"
    
    is_blacklisted = "No"
    for role in member.roles:
        if "blacklist" in role.name.lower():
            is_blacklisted = "Yes"
            break
            
    # 2. Account Information
    guild_name = ctx.guild.name
    joined_date = member.joined_at.strftime('%Y-%m-%d %H:%M:%S UTC') if member.joined_at else "Unknown"
    member_days = (datetime.now(timezone.utc) - member.joined_at).days if member.joined_at else 0
    created_date = member.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
    account_days = (datetime.now(timezone.utc) - member.created_at).days
    
    # 3. Roles
    member_roles = [role for role in reversed(member.roles) if role != ctx.guild.default_role]
    roles_count = len(member_roles)
    if roles_count > 0:
        roles_str = " ".join([role.mention for role in member_roles])
        if len(roles_str) > 1000:
            roles_str = roles_str[:997] + "..."
    else:
        roles_str = "No roles"
        
    # 4. Ticket Statistics
    tickets_opened = get_ticket_count(member.id)
    
    active_ticket = "No"
    active_channels = []
    for channel in ctx.guild.text_channels:
        if channel.category_id == CATEGORY_ID:
            parts = channel.name.split("-")
            if len(parts) >= 2 and parts[1].lower() == member.name.lower():
                active_ticket = "Yes"
                active_channels.append(channel.mention)
                
    ticket_history = ", ".join(active_channels) if active_channels else "None"
    
    # 5. Helper Information
    helper_role_ids = {1500199147859476604, 1500198955940712468, 1500198307257913544, 1505300013604147332, 1541834030717075457}
    helper_roles_held = [role.name for role in member.roles if role.id in helper_role_ids]
    helper_status = ", ".join(helper_roles_held) if helper_roles_held else "Not a helper"
    
    total_vouches = get_total_vouches(member.id)
            
    helper_rating = f"{total_vouches} vouches" if total_vouches > 0 else "No ratings"
    warnings_data = get_warnings(member.id)
    warnings = warnings_data.get("count", 0)
    
    # 6. Status
    is_timed_out = "Yes" if (member.is_timed_out() if hasattr(member, "is_timed_out") else False) else "No"
    is_booster = "Yes" if member.premium_since else "No"
    
    # Construct Embed
    embed = V2Embed(
        title=f"User Lookup: {display_name} 🦅",
        color=0x2b2d31
    )
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
        
    user_info_val = (
        f"**Username:** {username}\n"
        f"**Display Name:** {display_name} 🦅\n"
        f"**Discord ID:** `{discord_id}`\n"
        f"**Bot:** {is_bot}\n"
        f"**Blacklisted:** {is_blacklisted}"
    )
    embed.add_field(name="User Information", value=user_info_val, inline=False)
    
    acc_info_val = (
        f"**Joined {guild_name}:** {joined_date}\n"
        f"**Server Member For:** {member_days} days\n"
        f"**Account Created:** {created_date}\n"
        f"**Account Age:** {account_days} days"
    )
    embed.add_field(name="Account Information", value=acc_info_val, inline=False)
    
    embed.add_field(name=f"Roles ({roles_count})", value=roles_str, inline=False)
    
    ticket_stats_val = (
        f"**Tickets Opened:** {tickets_opened}\n"
        f"**Active Ticket:** {active_ticket}\n"
        f"**Ticket History:** {ticket_history}"
    )
    embed.add_field(name="Ticket Statistics", value=ticket_stats_val, inline=False)
    
    helper_info_val = (
        f"**Helper Status:** {helper_status}\n"
        f"**Helper Rating:** {helper_rating}\n"
        f"**Warnings:** {warnings}"
    )
    embed.add_field(name="Helper Information", value=helper_info_val, inline=True)
    
    status_val = (
        f"**Timed Out:** {is_timed_out}\n"
        f"**Booster:** {is_booster}"
    )
    embed.add_field(name="Status", value=status_val, inline=True)
    
    embed.set_footer(
        text=f"Lookup requested by {ctx.author.name} • Today at {datetime.now().strftime('%I:%M %p')}",
        icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None
    )
    
    await ctx.send(embed=embed, view=UserLookupView(member))

if __name__ == "__main__":
    if not TOKEN or TOKEN.lower().startswith("your_"):
        print("ERROR: DISCORD_TOKEN not found or is still using the example placeholder.")
        print("       Create a '.env' file in the discord bot folder or set the DISCORD_TOKEN environment variable.")
        print("       Copy '.env.example' to '.env' and replace the placeholder value with your bot token.")
        raise RuntimeError("DISCORD_TOKEN missing or placeholder value detected. Please configure your .env or environment variables.")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"ERROR: Failed to start bot: {e}")
        raise
