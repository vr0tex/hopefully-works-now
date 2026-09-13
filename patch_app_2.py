import re

with open("app.py.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update allowed_roles
content = re.sub(r'allowed_roles = \["als helper", "av helper", "ae helper"\]', 'allowed_roles = ["als helper", "av helper", "ae helper", "dqr helper"]', content)
content = re.sub(r'allowed_roles = \["als helper", "av helper", "utd helper", "ae helper"\]', 'allowed_roles = ["als helper", "av helper", "utd helper", "ae helper", "dqr helper"]', content)

# 2. Update game_image_names
content = re.sub(r'"AE": "ae\.jpg",?', '"AE": "ae.jpg",\n                "DQR": "dqr.png",', content)

# 3. Update loops over games
content = re.sub(r'for game in \["ALS", "AV", "UTD", "AE"\]:', 'for game in ["ALS", "AV", "UTD", "AE", "DQR"]:', content)
content = re.sub(r'for game in \["ALS", "AV", "AE"\]:', 'for game in ["ALS", "AV", "AE", "DQR"]:', content)

# 4. Update string format "+ Anime Expeditions (AE)"
content = re.sub(r'(f"\+ Anime Expeditions \(AE\)\\n")', r'\1\n        f"+ Dungeon Quest Reborn (DQR)\\n"', content)

# 5. Update game full names dict mapping
content = re.sub(r'"AE": "Anime Expeditions"\n\s*\}', '"AE": "Anime Expeditions",\n        "DQR": "Dungeon Quest Reborn"\n    }', content)

# 6. Update literal mapping if present (using re to match similar string)
content = re.sub(r"'AE': \"🎮\",?", '\'AE\': "🎮", \'DQR\': "🎮",', content)

with open("app.py.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Patched app.py.py for missing DQR entries")
