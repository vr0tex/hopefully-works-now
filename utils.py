import sys, types
sys.modules['audioop'] = types.ModuleType('audioop')
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps
import aiohttp
from io import BytesIO
import os

class V2Embed(discord.Embed):
    def __init__(self, **kwargs):
        kwargs.setdefault('color', 0x2b2d31) 
        super().__init__(**kwargs)

class EmbedFactory:
    @staticmethod
    def create_premium_embed(title, description, color=0x2b2d31):
        return V2Embed(title=f"**{title}**", description=description)

import textwrap
import datetime

async def create_vouch_card(booster_name, game_name, total_vouches, avatar_url, customer_name="Customer", customer_avatar=None, customer_feedback="Fast, safe, and professional!", booster_id="0000"):
    # Overall Canvas 1200x675
    base = Image.new('RGBA', (1200, 675), color=(18, 14, 20, 255))
    draw = ImageDraw.Draw(base)

    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 60)
        header_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 40)
        stat_value_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 55)
        text_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 25)
        small_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 16)
        star_font = ImageFont.truetype("C:/Windows/Fonts/seguisym.ttf", 40) # for stars
    except Exception:
        title_font = header_font = stat_value_font = text_font = small_font = star_font = ImageFont.load_default()

    # Header
    draw.text((40, 30), "PARADOX", font=title_font, fill=(255, 255, 255))
    draw.text((340, 40), "VOUCH", font=header_font, fill=(255, 105, 180))
    draw.line((40, 100, 1160, 100), fill=(255, 105, 180, 100), width=2)

    # Helper function for panels
    def draw_panel(xy, size, border_color=(255, 105, 180, 150)):
        x, y = xy
        w, h = size
        # Main background
        draw.rounded_rectangle([x, y, x+w, y+h], radius=15, fill=(25, 20, 28, 240), outline=border_color, width=2)
        # Inner highlight
        draw.rounded_rectangle([x+2, y+2, x+w-2, y+h-2], radius=13, outline=(255, 255, 255, 15), width=1)

    # Panel 1: Profile (Left)
    draw_panel((40, 130), (280, 500))
    
    # Load Avatar
    avatar_size = 160
    avatar_x, avatar_y = 100, 160
    
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status == 200:
                avatar_data = await resp.read()
                avatar = Image.open(BytesIO(avatar_data)).convert("RGBA")
                avatar = avatar.resize((avatar_size, avatar_size))
                mask = Image.new('L', (avatar_size, avatar_size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
                avatar.putalpha(mask)
                base.paste(avatar, (avatar_x, avatar_y), avatar)
                
                # Glowing border ring
                for i in range(4):
                    draw.ellipse((avatar_x - i, avatar_y - i, avatar_x + avatar_size + i, avatar_y + avatar_size + i), 
                                 outline=(255, 105, 180, 255 - (i*50)), width=1)

    # Booster info
    name_w = draw.textlength(booster_name, font=header_font)
    draw.text((40 + (280 - name_w)/2, 340), booster_name, font=header_font, fill=(255, 255, 255))
    
    role_text = f"{game_name} HELPER"
    role_w = draw.textlength(role_text, font=small_font)
    draw.text((40 + (280 - role_w)/2, 390), role_text, font=small_font, fill=(150, 150, 150))
    
    # Stars
    stars = "★ ★ ★ ★ ★"
    star_w = draw.textlength(stars, font=star_font)
    draw.text((40 + (280 - star_w)/2, 450), stars, font=star_font, fill=(255, 105, 180))
    
    draw.text((150, 520), "5.0", font=stat_value_font, fill=(255, 105, 180), anchor="mm")

    # Panel 2: Testimonial (Middle)
    draw_panel((340, 130), (520, 500), border_color=(80, 70, 90, 150))
    draw.text((360, 150), "CLIENT TESTIMONIAL", font=small_font, fill=(255, 105, 180))
    
    feedback_lines = textwrap.wrap(f"\"{customer_feedback}\"", width=23)
    y_fb = 200
    for line in feedback_lines[:4]:
        draw.text((360, y_fb), line, font=header_font, fill=(230, 230, 230))
        y_fb += 45
    
    # 5.0 circle in top right of middle panel
    draw.ellipse((750, 150, 830, 230), outline=(255, 215, 0), width=3, fill=(40, 35, 10, 200))
    draw.text((790, 190), "5.0", font=text_font, fill=(255, 215, 0), anchor="mm")
    
    # Bottom section of middle panel
    draw.rounded_rectangle([360, 530, 840, 610], radius=10, fill=(35, 30, 40, 200))
    
    if customer_avatar:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(customer_avatar) as resp:
                    if resp.status == 200:
                        c_avatar_data = await resp.read()
                        c_avatar = Image.open(BytesIO(c_avatar_data)).convert("RGBA")
                        c_avatar = c_avatar.resize((60, 60))
                        c_mask = Image.new('L', (60, 60), 0)
                        ImageDraw.Draw(c_mask).ellipse((0, 0, 60, 60), fill=255)
                        c_avatar.putalpha(c_mask)
                        base.paste(c_avatar, (370, 540), c_avatar)
        except Exception:
            pass

    draw.text((440, 550), customer_name, font=text_font, fill=(255, 255, 255))
    draw.text((440, 580), "Verified Feedback", font=small_font, fill=(150, 150, 150))

    # Panel 3: Stats (Right)
    draw.text((880, 140), "CARRY STATS", font=small_font, fill=(255, 105, 180))
    
    # Sub-panels in the right section
    def draw_stat_box(y, title, value, subtext):
        draw.rounded_rectangle([880, y, 1160, y+105], radius=10, fill=(25, 20, 28, 240), outline=(255, 105, 180, 80), width=1)
        draw.text((900, y+15), title, font=small_font, fill=(150, 150, 150))
        draw.text((900, y+40), value, font=header_font, fill=(255, 105, 180))
        draw.text((900, y+80), subtext, font=small_font, fill=(100, 100, 100))

    draw_stat_box(180, "TOTAL VOUCHES", str(total_vouches), "Lifetime sessions")
    draw_stat_box(300, "AVG RATING", "4.9 / 5", "Average score")
    
    # Green stat box
    draw.rounded_rectangle([880, 420, 1160, 525], radius=10, fill=(20, 25, 25, 240), outline=(0, 255, 150, 80), width=1)
    draw.text((900, 435), "5-STAR RATE", font=small_font, fill=(150, 150, 150))
    draw.text((900, 460), "98%", font=header_font, fill=(0, 255, 150))
    draw.text((900, 500), "Perfect score rate", font=small_font, fill=(100, 100, 100))
    
    # Top Service
    draw.rounded_rectangle([880, 540, 1160, 630], radius=10, fill=(25, 20, 28, 240), outline=(100, 100, 100, 80), width=1)
    draw.text((900, 550), "TOP SERVICE", font=small_font, fill=(150, 150, 150))
    draw.text((900, 575), f"{game_name}", font=text_font, fill=(255, 255, 255))
    draw.text((900, 605), "Primary game", font=small_font, fill=(100, 100, 100))

    # Bottom Text
    current_date = datetime.datetime.now().strftime("%d %b %Y")
    bottom_left_text = f"Issued {current_date} • Helper {booster_id} • paradoxapplication.xyz"
    draw.text((40, 645), bottom_left_text, font=small_font, fill=(100, 100, 100))
    
    bottom_right_text = "PARADOX SERVICE"
    draw.text((1160, 645), bottom_right_text, font=small_font, fill=(100, 100, 100), anchor="ra")

    img_byte_arr = BytesIO()
    base.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

async def create_profile_card(booster_name, total_vouches, game_breakdown, avatar_url):
    # Overall Canvas 1200x675
    base = Image.new('RGBA', (1200, 675), color=(18, 14, 20, 255))
    draw = ImageDraw.Draw(base)

    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 60)
        header_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 40)
        stat_value_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 55)
        text_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 25)
        small_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 16)
        star_font = ImageFont.truetype("C:/Windows/Fonts/seguisym.ttf", 40)
    except Exception:
        title_font = header_font = stat_value_font = text_font = small_font = star_font = ImageFont.load_default()

    # Header
    draw.text((40, 30), "PARADOX", font=title_font, fill=(255, 255, 255))
    draw.text((340, 40), "PROFILE", font=header_font, fill=(0, 255, 255))
    draw.line((40, 100, 1160, 100), fill=(0, 255, 255, 100), width=2)

    def draw_panel(xy, size, border_color=(0, 255, 255, 150)):
        x, y = xy
        w, h = size
        draw.rounded_rectangle([x, y, x+w, y+h], radius=15, fill=(25, 20, 28, 240), outline=border_color, width=2)
        draw.rounded_rectangle([x+2, y+2, x+w-2, y+h-2], radius=13, outline=(255, 255, 255, 15), width=1)

    # Panel 1: Profile (Left)
    draw_panel((40, 130), (280, 500))
    
    avatar_size = 160
    avatar_x, avatar_y = 100, 160
    
    async with aiohttp.ClientSession() as session:
        async with session.get(avatar_url) as resp:
            if resp.status == 200:
                avatar_data = await resp.read()
                avatar = Image.open(BytesIO(avatar_data)).convert("RGBA")
                avatar = avatar.resize((avatar_size, avatar_size))
                mask = Image.new('L', (avatar_size, avatar_size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
                avatar.putalpha(mask)
                base.paste(avatar, (avatar_x, avatar_y), avatar)
                for i in range(4):
                    draw.ellipse((avatar_x - i, avatar_y - i, avatar_x + avatar_size + i, avatar_y + avatar_size + i), 
                                 outline=(0, 255, 255, 255 - (i*50)), width=1)

    name_w = draw.textlength(booster_name, font=header_font)
    draw.text((40 + (280 - name_w)/2, 340), booster_name, font=header_font, fill=(255, 255, 255))
    draw.text((40 + (280 - draw.textlength("PARADOX HELPER", font=small_font))/2, 390), "PARADOX HELPER", font=small_font, fill=(150, 150, 150))
    
    stars = "★ ★ ★ ★ ★"
    star_w = draw.textlength(stars, font=star_font)
    draw.text((40 + (280 - star_w)/2, 450), stars, font=star_font, fill=(0, 255, 255))
    draw.text((150, 520), "5.0", font=stat_value_font, fill=(0, 255, 255), anchor="mm")

    # Panel 2: Achievements (Middle)
    draw_panel((340, 130), (520, 500), border_color=(80, 70, 90, 150))
    draw.text((360, 150), "ACHIEVEMENTS", font=small_font, fill=(0, 255, 255))
    
    achievements = [
        (1, "🌱 First Steps", "Earned your first vouch"),
        (25, "🔥 Trusted Booster", "Reached 25 vouches"),
        (100, "👑 Elite Carrier", "Reached 100 vouches"),
        (500, "🌟 Hall of Fame", "Reached 500 vouches"),
    ]
    
    y_ach = 200
    for threshold, name, desc in achievements:
        unlocked = total_vouches >= threshold
        color = (255, 255, 255) if unlocked else (100, 100, 100)
        draw.text((370, y_ach), f"{name}{' ✅' if unlocked else ' 🔒'}", font=text_font, fill=color)
        draw.text((370, y_ach + 35), f"— {desc}", font=small_font, fill=color)
        y_ach += 75

    # Panel 3: Stats (Right)
    draw.text((880, 140), "CARRY STATS", font=small_font, fill=(0, 255, 255))
    
    def draw_stat_box(y, title, value, subtext, color=(0, 255, 255)):
        draw.rounded_rectangle([880, y, 1160, y+105], radius=10, fill=(25, 20, 28, 240), outline=(*color, 80), width=1)
        draw.text((900, y+15), title, font=small_font, fill=(150, 150, 150))
        draw.text((900, y+40), value, font=header_font, fill=color)
        draw.text((900, y+80), subtext, font=small_font, fill=(100, 100, 100))

    draw_stat_box(180, "TOTAL VOUCHES", str(total_vouches), "Lifetime sessions")
    draw_stat_box(300, "AVG RATING", "5.0 / 5", "Average score")
    draw_stat_box(420, "5-STAR RATE", "100%", "Perfect score rate", color=(0, 255, 150))
    
    top_game = max(game_breakdown.items(), key=lambda x: x[1])[0] if game_breakdown else "None"
    draw_stat_box(540, "TOP SERVICE", top_game, "Primary game")

    # Footer
    footer_text = f"Issued {datetime.datetime.now().strftime('%d %b %Y')} • paradoxapplication.xyz"
    draw.text((40, 645), footer_text, font=small_font, fill=(100, 100, 100))
    draw.text((1160, 645), "PARADOX SERVICE", font=small_font, fill=(100, 100, 100), anchor="ra")

    img_byte_arr = BytesIO()
    base.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

