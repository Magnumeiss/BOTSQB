import os
import sys
import json
import requests

API_URL = "https://warthunder.com/en/api/replay"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://warthunder.com",
    "Referer": "https://warthunder.com/en/tournament/replay/"
}


def load_cookies():
    """
    Loads cookies from auth_cookie.json.
    Supports dictionary format or raw array exports from Cookie Editor.
    """
    with open("auth_cookie.json", "r") as f:
        data = json.load(f)

    if isinstance(data, list):
        return {item["name"]: item["value"] for item in data if "name" in item and "value" in item}
    return data


def fetch_replays_from_api(page_num, cookies, game_type="clanBattle"):
    """
    Queries the War Thunder JSON API endpoint for replays.
    'clanBattle' = Squadron Battles
    """
    payload = {
        "gameMode": ["arcade", "realistic", "simulation"],
        "gameType": game_type,
        "techType": "all",
        "findMissionValue": "",
        "findUserValue": "",
        "findUserType": "USERNAME",
        "isUserOwnReplays": False,
        "rankRange": "",
        "timeRangeFrom": "",
        "timeRangeTo": "",
        "limit": 20,
        "page": page_num
    }

    print(f"[*] Querying API page {page_num}...")
    response = requests.post(API_URL, json=payload, cookies=cookies, headers=HEADERS)

    if response.status_code != 200:
        print(f"  [!] API returned HTTP {response.status_code}: {response.text[:300]}")
        return []

    try:
        data = response.json()
    except Exception as e:
        print(f"  [!] Failed to parse JSON response: {e}")
        return []

    if isinstance(data, dict):
        items = data.get("data") or data.get("replays") or data.get("list") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    print(f"  [+] API returned {len(items)} replay(s) on page {page_num}.")
    return items


def download_replay_files(replay_id, cookies):
    """
    Downloads ONLY 0001.wrpl into a folder named after the replay ID.
    War Thunder CDN URL: https://wt-game-replays.warthunder.com/<hex_id>/0001.wrpl
    """
    try:
        hex_id = f"{int(replay_id):016x}"
    except ValueError:
        hex_id = str(replay_id)

    folder_path = str(replay_id)
    os.makedirs(folder_path, exist_ok=True)

    part_str = "0001"
    file_url = f"https://wt-game-replays.warthunder.com/{hex_id}/{part_str}.wrpl"
    file_path = os.path.join(folder_path, f"{part_str}.wrpl")

    # Skip if file already downloaded
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        print(f"  [*] {part_str}.wrpl already exists in ./{folder_path}/, skipping.")
        return

    print(f"[*] Fetching {part_str}.wrpl for Replay ID {replay_id} (Hex: {hex_id})...")
    res = requests.get(file_url, cookies=cookies, headers=HEADERS, stream=True)

    if res.status_code == 200:
        with open(file_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  [+] Saved ./{folder_path}/{part_str}.wrpl")
    elif res.status_code in (404, 403):
        print(f"  [-] Could not find {part_str}.wrpl on CDN (HTTP {res.status_code}).")
    else:
        print(f"  [-] HTTP {res.status_code} while fetching {part_str}.wrpl")


def main():
    try:
        num_pages = int(sys.argv[1])
    except (IndexError, ValueError):
        num_pages = 1

    try:
        cookies = load_cookies()
        print(f"[*] Loaded cookies: {list(cookies.keys())}")
    except FileNotFoundError:
        print("Error: auth_cookie.json file not found.")
        return

    all_replays = []
    for page in range(1, num_pages + 1):
        replays = fetch_replays_from_api(page_num=page, cookies=cookies, game_type="clanBattle")
        all_replays.extend(replays)

    print(f"\nTotal Replays Retrieved: {len(all_replays)}")

    for idx, replay in enumerate(all_replays, start=1):
        if isinstance(replay, dict):
            r_id = replay.get("id") or replay.get("replay_id") or replay.get("external_id")
            title = replay.get("title") or replay.get("mission") or f"Replay_{r_id}"
        else:
            r_id = str(replay)
            title = f"Replay_{r_id}"

        if not r_id:
            continue

        print(f"\n[{idx}/{len(all_replays)}] {title} (ID: {r_id})")
        download_replay_files(r_id, cookies)


if __name__ == "__main__":
    main()