import os
import re
import json
import asyncio
import requests
import discord
from discord.ext import tasks, commands

# CONFIGURATION FILES
CONFIG_PATH = "config.json"
GERMAN_JSON_PATH = "german.json"
AUTH_COOKIE_PATH = "auth_cookie.json"

API_URL = "https://warthunder.com/en/api/replay"
GAME_TYPE = "clanBattle"  # "clanBattle" = Squadron Battles

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://warthunder.com",
    "Referer": "https://warthunder.com/en/tournament/replay/"
}

IGNORE_KEYWORDS = {
    "http", "https", "warthunder", "wt-game-replays", "arcade", "realistic",
    "simulation", "clanbattle", "domination", "conquest", "battle", "mission",
    "author", "type", "version", "level", "game", "user", "name", "clan",
    "gamedata", "levels", "units", "weapons", "gui", "scripts", "common",
    "tex", "bin", "blk", "dds", "tanks", "planes", "ships", "coop", "event",
    "armored", "falklands", "normandy", "bfd", "norespawn", "cta"
}


def load_json_file(filepath):
    if not os.path.exists(filepath):
        print(f"[!] Warning: File '{filepath}' not found.")
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def load_cookies():
    data = load_json_file(AUTH_COOKIE_PATH)
    if isinstance(data, list):
        return {item["name"]: item["value"] for item in data if "name" in item and "value" in item}
    return data


def load_german_json():
    data = load_json_file(GERMAN_JSON_PATH)
    id_to_display = {}
    vehicles_dict = data.get("vehicles", {})
    if isinstance(vehicles_dict, dict):
        for category, item_dict in vehicles_dict.items():
            if isinstance(item_dict, dict):
                for display_name, internal_id in item_dict.items():
                    if isinstance(internal_id, str) and len(internal_id) > 2:
                        id_to_display[internal_id] = display_name
    return id_to_display


def decompress_wrpl(raw_bytes):
    decompressed = bytearray(raw_bytes)
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        zstd_magic = b'\x28\xb5\x2f\xfd'
        for m in re.finditer(re.escape(zstd_magic), raw_bytes):
            try:
                decomp = dctx.decompress(raw_bytes[m.start():], max_output_size=15 * 1024 * 1024)
                decompressed.extend(decomp)
            except Exception:
                pass
    except ImportError:
        pass
    return bytes(decompressed)


def is_valid_player_name(token, id_to_display):
    if token in id_to_display:
        return False
    if '/' in token or '\\' in token:
        return False
    if token.lower().endswith(('.blk', '.bin', '.dds', '.nut', '.tga', '.png')):
        return False
    token_lower = token.lower()
    if any(kw in token_lower for kw in IGNORE_KEYWORDS):
        return False
    if len(token) < 3 or len(token) > 32:
        return False
    return True


def parse_lineup_in_memory(stream_data, id_to_display):
    raw_tokens = [s.decode('utf-8', errors='ignore') for s in re.findall(b'[A-Za-z0-9_\\-\\./@]{3,}', stream_data)]

    v_indices = [idx for idx, token in enumerate(raw_tokens) if token in id_to_display]
    if not v_indices:
        return []

    best_cluster = (0, 0, 0)
    for i in range(len(v_indices)):
        j = i
        while j < len(v_indices) and (v_indices[j] - v_indices[i]) <= 150:
            j += 1
        count = j - i
        if count > best_cluster[0]:
            best_cluster = (count, v_indices[i], v_indices[j - 1])

    if best_cluster[0] == 0:
        return []

    start_idx = max(0, best_cluster[1] - 20)
    end_idx = min(len(raw_tokens), best_cluster[2] + 25)
    cluster_tokens = raw_tokens[start_idx:end_idx]

    found_vehicles = []
    for token in cluster_tokens:
        if token in id_to_display and token not in found_vehicles:
            found_vehicles.append(token)

    found_players = []
    for token in cluster_tokens:
        if is_valid_player_name(token, id_to_display) and token not in found_players:
            found_players.append(token)

    lineup = []
    limit = min(len(found_players), len(found_vehicles))
    for i in range(limit):
        v_id = found_vehicles[i]
        lineup.append({
            "player_name": found_players[i],
            "vehicle_id": v_id,
            "vehicle_name": id_to_display.get(v_id, v_id)
        })

    return lineup


def fetch_latest_replay_data(last_processed_id, cookies, id_to_display):
    """
    Checks API for newest replay. If it's a new ID, downloads and parses 0001.wrpl in RAM.
    """
    payload = {
        "gameMode": ["arcade", "realistic", "simulation"],
        "gameType": GAME_TYPE,
        "techType": "all",
        "findMissionValue": "",
        "findUserValue": "",
        "findUserType": "USERNAME",
        "isUserOwnReplays": False,
        "limit": 1,
        "page": 1
    }

    try:
        res = requests.post(API_URL, json=payload, cookies=cookies, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[!] API HTTP {res.status_code}")
            return None

        data = res.json()
        items = data.get("data") or data.get("replays") or data.get("list") or data.get("items") or []
        if not items:
            return None

        newest = items[0]
        r_id = str(newest.get("id") or newest.get("replay_id") or newest.get("external_id"))

        # Skip if we already processed this replay ID
        if r_id == str(last_processed_id):
            return None

        title = newest.get("title") or newest.get("mission") or f"Replay_{r_id}"

        try:
            hex_id = f"{int(r_id):016x}"
        except ValueError:
            hex_id = str(r_id)

        parts_to_try = ["0001", "0000", "0002"]
        lineup = []
        used_part = ""

        for part_str in parts_to_try:
            file_url = f"https://wt-game-replays.warthunder.com/{hex_id}/{part_str}.wrpl"
            wrpl_res = requests.get(file_url, cookies=cookies, headers=HEADERS, timeout=10)
            if wrpl_res.status_code != 200:
                continue

            stream_data = decompress_wrpl(wrpl_res.content)
            lineup = parse_lineup_in_memory(stream_data, id_to_display)

            if lineup:
                used_part = f"{part_str}.wrpl"
                break

        return r_id, title, used_part, lineup

    except Exception as e:
        print(f"[!] Error checking replay: {e}")
        return None


# DISCORD BOT INITIALIZATION
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

last_processed_replay_id = None
config = load_json_file(CONFIG_PATH)
cookies = load_cookies()
id_to_display = load_german_json()

CHECK_INTERVAL = config.get("check_interval_seconds", 120)  # Default: 2 mins
CHANNEL_ID = config.get("channel_id")
BOT_TOKEN = config.get("bot_token")


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_for_new_replays():
    global last_processed_replay_id

    if not CHANNEL_ID:
        print("[!] Error: 'channel_id' is missing in config.json")
        return

    # Run network request and parsing in thread to avoid freezing bot
    result = await asyncio.to_thread(
        fetch_latest_replay_data, last_processed_replay_id, cookies, id_to_display
    )

    if not result:
        return

    r_id, title, used_part, lineup = result
    last_processed_replay_id = r_id

    # Find target channel
    channel = bot.get_channel(int(CHANNEL_ID))
    if not channel:
        try:
            channel = await bot.fetch_channel(int(CHANNEL_ID))
        except Exception as e:
            print(f"[!] Could not find channel {CHANNEL_ID}: {e}")
            return

    # Format Markdown Message
    msg = f"🎮 **New War Thunder Replay Detected!** — `{title}` (ID: `{r_id}`)\n"
    msg += f"**Players:** `{len(lineup)}` | **Source:** `{used_part or 'N/A'}`\n```\n"

    if lineup:
        for p in lineup:
            msg += f"{p['player_name']:<22} -> {p['vehicle_name']} ({p['vehicle_id']})\n"
    else:
        msg += "No lineup summary block extracted for this replay.\n"

    msg += "```"

    await channel.send(msg)
    print(f"[+] Posted new replay ID '{r_id}' ({len(lineup)} players) to Discord channel {CHANNEL_ID}.")


@check_for_new_replays.before_loop
async def before_check():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"[+] Bot logged in as: {bot.user} (ID: {bot.user.id})")
    if not check_for_new_replays.is_running():
        check_for_new_replays.start()
        print(f"[*] Started automatic replay watcher loop (Interval: {CHECK_INTERVAL}s).")


def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("[!] Please set a valid 'bot_token' and 'channel_id' in config.json!")
        return

    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()