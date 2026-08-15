import os
import re
import json

ENVIRONMENT_FILTER_REGEX = re.compile(
    r'(spawn|zone|airfield|artillery|respawn|bot|ai_|_defence|37mm_61kO|40mm|flak|fortification|capsule|trigger)',
    re.IGNORECASE
)

# Matching War Thunder internal vehicle identifiers across ground, air, naval
REAL_VEHICLE_REGEX = re.compile(
    r'^(germ_|us_|ussr_|il_|uk_|jp_|cn_|fr_|it_|se_|f_|g_|yak_|uss_|hms_|ijn_|km_)[A-Za-z0-9_]+',
    re.IGNORECASE
)

KNOWN_VEHICLES_KW = {
    "begleitpanzer", "merkava", "hunter", "kpz", "phantom", "mbt", "yak",
    "magach", "gepard", "bmd", "xm1", "flakpz", "leopard", "t_80", "t_72", "abrams", "g_91"
}


def load_german_json(filepath="german.json"):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        id_to_display = {}
        vehicles_dict = data.get("vehicles", {})
        if isinstance(vehicles_dict, dict):
            for category, item_dict in vehicles_dict.items():
                if isinstance(item_dict, dict):
                    for display_name, internal_id in item_dict.items():
                        if isinstance(internal_id, str):
                            id_to_display[internal_id] = display_name
        return id_to_display
    except Exception:
        return {}


def format_vehicle_display(v_id, id_to_display):
    if v_id in id_to_display:
        return id_to_display[v_id]

    clean_id = v_id
    prefixes = ["germ_", "us_", "ussr_", "il_", "uk_", "jp_", "cn_", "fr_", "it_", "se_"]
    for p in prefixes:
        if clean_id.lower().startswith(p):
            clean_id = clean_id[len(p):]
            break

    clean_id = clean_id.replace("_", " ").title()
    clean_id = re.sub(r'\bMk\b', 'Mk.', clean_id, flags=re.IGNORECASE)
    clean_id = re.sub(r'\bF (\d+)\b', r'F.\1', clean_id, flags=re.IGNORECASE)
    return clean_id


def decompress_all_wrpl_files():
    files = sorted([f for f in os.listdir('.') if f.lower().endswith('.wrpl')])
    if not files:
        return {}
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
    except ImportError:
        dctx = None

    decompressed_files = {}
    for fname in files:
        with open(fname, 'rb') as f:
            data = f.read()
        combined = bytearray(data)
        if dctx:
            zstd_magic = b'\x28\xb5\x2f\xfd'
            for m in re.finditer(re.escape(zstd_magic), data):
                try:
                    decomp = dctx.decompress(data[m.start():], max_output_size=15 * 1024 * 1024)
                    if decomp:
                        combined.extend(decomp)
                except Exception:
                    pass
        decompressed_files[fname] = bytes(combined)
    return decompressed_files


def is_vehicle_id(token, id_to_display):
    if ENVIRONMENT_FILTER_REGEX.search(token):
        return False
    if token in id_to_display or REAL_VEHICLE_REGEX.match(token):
        return True
    return any(kw in token.lower() for kw in KNOWN_VEHICLES_KW)


def is_valid_player_name(clean_token):
    if ENVIRONMENT_FILTER_REGEX.search(clean_token):
        return False
    ignore_words = {
        "clanbattle", "realistic", "arcade", "simulation", "gamedata", "levels",
        "units", "weapons", "gui", "scripts", "common", "tex", "bin", "blk",
        "dds", "tanks", "planes", "ships", "coop", "event", "armored", "falklands",
        "normandy", "bfd", "norespawn", "cta", "domination", "conquest", "battle",
        "author", "version", "user", "name", "clan", "http", "https", "warthunder",
        "matchinginfo", "player", "clantag", "userid", "squadid", "teama", "teamb"
    }
    if clean_token.lower() in ignore_words or len(clean_token) < 2 or len(clean_token) > 25:
        return False
    if '/' in clean_token or '\\' in clean_token or clean_token.isdigit() or clean_token.startswith("array"):
        return False
    return True


def parse_squadron_battle():
    id_to_display = load_german_json("german.json")
    decompressed_files = decompress_all_wrpl_files()
    if not decompressed_files:
        print("[!] No .wrpl files found in current directory.")
        return {}

    target_fname = None
    target_data = None
    for fname, stream_bytes in decompressed_files.items():
        if b"matchingInfo" in stream_bytes or b"clanTag" in stream_bytes:
            target_fname = fname
            target_data = stream_bytes
            break

    if not target_data:
        target_fname, target_data = max(decompressed_files.items(), key=lambda x: len(x[1]))

    # Python 3.13 compliant byte pattern using rb'...' and \x80-\xff
    player_pattern = re.compile(rb'([A-Za-z0-9_\-\x80-\xff]{2,25})(@live|@steam|@psn|@xbox|@ptv)?')

    squadron_counts = {}
    seen_players = set()
    player_records = []

    # Step 1: Locate player accounts and their exact binary byte start positions
    for m in player_pattern.finditer(target_data):
        p_raw = m.group(1).decode('utf-8', errors='ignore')
        p_clean = p_raw.replace("ツ", "")

        if not is_valid_player_name(p_clean) or is_vehicle_id(p_clean, id_to_display):
            continue

        byte_offset = m.start()

        # Check immediate 150-byte window after player offset for squadron tag
        proximity_chunk = target_data[byte_offset: byte_offset + 150]
        tokens_near = re.findall(rb'[A-Za-z0-9_]{2,12}', proximity_chunk)

        found_tag = None
        for tok in tokens_near:
            tok_str = tok.decode('utf-8', errors='ignore')
            if (2 <= len(tok_str) <= 6 and tok_str.isalnum() and not tok_str.isdigit()
                    and not is_vehicle_id(tok_str, id_to_display)
                    and tok_str.lower() not in {"team", "array", "player", "name", "clan", "unit", "teama", "teamb"}
                    and tok_str != p_clean):
                found_tag = tok_str
                break

        if found_tag and p_clean not in seen_players:
            seen_players.add(p_clean)
            squadron_counts[found_tag] = squadron_counts.get(found_tag, 0) + 1
            player_records.append({
                "player_name": p_clean,
                "squadron": found_tag,
                "byte_offset": byte_offset
            })

    # Active 8v8 squadrons are tags with >= 4 players
    active_squadrons = {tag for tag, count in squadron_counts.items() if count >= 4}
    active_player_records = [r for r in player_records if r["squadron"] in active_squadrons]

    # Sort player records strictly by byte offset position in the binary
    active_player_records.sort(key=lambda x: x["byte_offset"])

    # Step 2: Extract active spawned vehicle strictly within each player's BINARY RECORD SLICE
    squadrons_output = {tag: [] for tag in active_squadrons}

    for i, rec in enumerate(active_player_records):
        p_name = rec["player_name"]
        tag = rec["squadron"]
        start_pos = rec["byte_offset"]

        # Slice binary stream from current player's offset to the next player's offset
        if i < len(active_player_records) - 1:
            end_pos = active_player_records[i + 1]["byte_offset"]
        else:
            end_pos = min(len(target_data), start_pos + 1200)

        player_binary_slice = target_data[start_pos:end_pos]

        # Extract tokens strictly inside this isolated player slice
        slice_tokens = [t.decode('utf-8', errors='ignore') for t in
                        re.findall(rb'[A-Za-z0-9_\-]{3,}', player_binary_slice)]

        slice_vehicles = [t for t in slice_tokens if is_vehicle_id(t, id_to_display)]

        # Determine spawned match vehicle
        spawned_vehicle = "unknown"
        if slice_vehicles:
            for v_cand in slice_vehicles:
                if REAL_VEHICLE_REGEX.match(v_cand) or v_cand in id_to_display:
                    spawned_vehicle = v_cand
                    break
            if spawned_vehicle == "unknown":
                spawned_vehicle = slice_vehicles[0]

        v_display = format_vehicle_display(spawned_vehicle, id_to_display)

        squadrons_output[tag].append({
            "player_name": p_name,
            "squadron": tag,
            "vehicle_id": spawned_vehicle,
            "vehicle_name": v_display
        })

    total_extracted = sum(len(v) for v in squadrons_output.values())

    print("\n==================================================")
    print(f" SQUADRON BATTLE REPLAY PARSED: {target_fname}")
    print(f" Active Squadrons: {list(active_squadrons)}")
    print(f" Total Players Found: {total_extracted} / 16")
    print("==================================================\n")

    for sq_tag, players in squadrons_output.items():
        print(f"SQUADRON [{sq_tag}] ({len(players)} Players)")
        for p in players:
            print(f"  {p['player_name']:<22} -> {p['vehicle_name']} ({p['vehicle_id']})")
        print()

    output_data = {
        "source_file": target_fname,
        "total_players": total_extracted,
        "squadrons": squadrons_output
    }

    return output_data


if __name__ == "__main__":
    parsed_res = parse_squadron_battle()
    with open("squadron_battle_output.json", "w", encoding="utf-8") as f:
        json.dump(parsed_res, f, indent=2, ensure_ascii=False)