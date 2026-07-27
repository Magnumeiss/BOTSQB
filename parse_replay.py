import os
import re
import json
import requests

WEBHOOK_URL = "https://discord.com/api/webhooks/1531415196323545259/GvEJ8NtYZDeKiotyGJ2TVITRDOMzKFTHECWfm8XKITugf0U5keNsl6zjLdidjBmHa9F8"

IGNORE_KEYWORDS = {
    "http", "https", "warthunder", "wt-game-replays", "arcade", "realistic",
    "simulation", "clanbattle", "domination", "conquest", "battle", "mission",
    "author", "type", "version", "level", "game", "user", "name", "clan"
}


def load_german_json(filepath="german.json"):
    """
    Loads german.json to map internal vehicle IDs to display names.
    """
    if not os.path.exists(filepath):
        print(f"[!] '{filepath}' not found in current directory.")
        return {}

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    id_to_display = {}
    vehicles_dict = data.get("vehicles", {})
    if isinstance(vehicles_dict, dict):
        for category, item_dict in vehicles_dict.items():
            if isinstance(item_dict, dict):
                for display_name, internal_id in item_dict.items():
                    if isinstance(internal_id, str) and len(internal_id) > 2:
                        id_to_display[internal_id] = display_name

    print(f"[+] Loaded {len(id_to_display)} vehicle definitions from '{filepath}'")
    return id_to_display


def decompress_wrpl(file_path):
    """
    Decompresses all Zstandard blocks in a .wrpl file into a byte stream.
    """
    if not os.path.exists(file_path):
        return b""

    with open(file_path, 'rb') as f:
        raw_data = f.read()

    decompressed = bytearray(raw_data)
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        zstd_magic = b'\x28\xb5\x2f\xfd'
        for m in re.finditer(re.escape(zstd_magic), raw_data):
            try:
                decomp = dctx.decompress(raw_data[m.start():], max_output_size=15 * 1024 * 1024)
                decompressed.extend(decomp)
            except Exception:
                pass
    except ImportError:
        pass

    return bytes(decompressed)


def extract_lineup_from_wrpl(file_path, id_to_display):
    """
    Dynamically finds vehicle IDs in the byte stream, creates a snippet window,
    and pairs players with their vehicles.
    """
    stream_data = decompress_wrpl(file_path)
    if not stream_data:
        return []

    # 1. Locate all vehicle ID byte occurrences in the stream
    vehicle_occurrences = []
    for v_id, display_name in id_to_display.items():
        if not isinstance(v_id, str):
            continue

        try:
            v_bytes = v_id.encode('utf-8')
        except Exception:
            continue

        pos = stream_data.find(v_bytes)
        while pos != -1:
            vehicle_occurrences.append((pos, v_id, display_name))
            pos = stream_data.find(v_bytes, pos + len(v_bytes))

    if not vehicle_occurrences:
        return []

    # Sort occurrences by position in the binary file
    vehicle_occurrences.sort(key=lambda x: x[0])

    # 2. Extract snippet window around the summary block
    first_pos = vehicle_occurrences[0][0]
    last_pos = vehicle_occurrences[-1][0]

    snippet_start = max(0, first_pos - 600)
    snippet_end = min(len(stream_data), last_pos + 1200)
    snippet = stream_data[snippet_start:snippet_end]

    # Extract ASCII/UTF-8 tokens from snippet
    raw_tokens = [s.decode('utf-8', errors='ignore') for s in re.findall(b'[A-Za-z0-9_\\-\\./@]{3,}', snippet)]

    # 3. Collect unique vehicles in order of appearance
    found_vehicles = []
    for token in raw_tokens:
        if token in id_to_display and token not in found_vehicles:
            found_vehicles.append(token)

    # 4. Collect potential player names in order of appearance
    found_players = []
    for token in raw_tokens:
        token_lower = token.lower()
        if (token not in id_to_display and
            not any(kw in token_lower for kw in IGNORE_KEYWORDS) and
            token not in found_players):
            found_players.append(token)

    # 5. Pair 1:1
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


def send_markdown_to_discord(parsed_replays):
    """
    Sends Discord Markdown formatted summary messages and attaches parsed_replays.json.
    """
    print("\n[*] Sending Discord Markdown report to webhook...")

    header_md = (
        f"# 🎮 War Thunder Replay Lineup Report\n"
        f"**Replays Processed:** `{len(parsed_replays)}` | **Status:** `Success`\n"
        f"──────────────────────────────────────────────\n"
    )

    chunks = [header_md]
    current_chunk = header_md

    for replay in parsed_replays:
        r_id = replay["replay_id"]
        players = replay["players"]

        replay_md = f"### 📁 Replay ID: `{r_id}`\n"
        replay_md += f"**Size:** `{replay['file_size_kb']} KB` | **Players:** `{len(players)}` \n```\n"

        if players:
            for p in players:
                replay_md += f"{p['player_name']:<22} -> {p['vehicle_name']} ({p['vehicle_id']})\n"
        else:
            replay_md += "No lineup summary block extracted for this file.\n"

        replay_md += "```\n"

        # Split into <2000 character chunks for Discord limit
        if len(current_chunk) + len(replay_md) > 1900:
            chunks.append(replay_md)
            current_chunk = replay_md
        else:
            chunks[-1] += replay_md
            current_chunk += replay_md

    # POST Markdown chunks to Discord
    for idx, chunk in enumerate(chunks, start=1):
        payload = {"content": chunk}
        res = requests.post(WEBHOOK_URL, json=payload)
        if res.status_code in (200, 204):
            print(f"  [+] Sent Markdown message chunk {idx}/{len(chunks)}")
        else:
            print(f"  [!] Failed chunk {idx}: HTTP {res.status_code}")

    # Attach parsed_replays.json file
    output_filename = "parsed_replays.json"
    try:
        with open(output_filename, "rb") as f:
            res = requests.post(
                WEBHOOK_URL,
                data={"payload_json": json.dumps({"content": "📎 **Attached Full JSON Dataset:**"})},
                files={"file": (output_filename, f, "application/json")}
            )
        if res.status_code in (200, 204):
            print("  [+] Successfully attached parsed_replays.json to Discord.")
    except Exception as e:
        print(f"  [!] Could not attach JSON file: {e}")


def main():
    id_to_display = load_german_json("german.json")

    folders = [d for d in os.listdir('.') if os.path.isdir(d)]
    parsed_replays = []

    print(f"\n[*] Processing {len(folders)} replay folder(s)...")

    for folder in sorted(folders):
        wrpl_path = os.path.join(folder, "0001.wrpl")
        if not os.path.exists(wrpl_path):
            continue

        size_kb = round(os.path.getsize(wrpl_path) / 1024, 2)
        lineup = extract_lineup_from_wrpl(wrpl_path, id_to_display)

        replay_entry = {
            "replay_id": folder,
            "file_size_kb": size_kb,
            "num_players": len(lineup),
            "players": lineup
        }
        parsed_replays.append(replay_entry)
        print(f"  [+] Replay ID '{folder}': {len(lineup)} player/vehicle match(es)")

    output_filename = "parsed_replays.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(parsed_replays, f, indent=4, ensure_ascii=False)

    print(f"\n[+] Saved parsed output to '{output_filename}'")

    if parsed_replays:
        send_markdown_to_discord(parsed_replays)


if __name__ == "__main__":
    main()