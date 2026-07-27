import os
import re
import sys
import json

KNOWN_PLAYERS = [
    "TrentSAS", "Lieutenant_Brage", "Grav_en", "Nexus___",
    "Last_Gunfighter_", "Lamoan", "Kafiツ", "BlastercasiX",
    "mati_gamming", "Orc", "MovableJet236@live", "Gas_Gas_V3",
    "meckerndes_schaf", "AUnderperformer", "BarkoThundo", "Real_Aquakid"
]

NAME_VARIANTS = {
    "mati_gamming": "mati_gamming",
    "MovableJet236": "MovableJet236@live",
    "Grav_en": "Grav_en",
    "Last_Gunfighter_": "Last_Gunfighter_",
    "Kafi": "Kafiツ",
    "meckerndes_schaf": "meckerndes_schaf",
    "BarkoThundo": "BarkoThundo",
    "0rc": "Orc",
    "Orc": "Orc",
    "Gas_Gas_V3": "Gas_Gas_V3",
    "AUnderperformer": "AUnderperformer",
    "Lieutenant_Brage": "Lieutenant_Brage",
    "Nexus____": "Nexus___",
    "Nexus___": "Nexus___",
    "Lamoan": "Lamoan",
    "BlastercasiX": "BlastercasiX",
    "Real_Aquakid": "Real_Aquakid",
    "TrentSAS": "TrentSAS"
}


def load_german_json(filepath="german.json"):
    """
    Loads vehicle display names from german.json.
    """
    if not os.path.exists(filepath):
        return {}

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


def decompress_single_file(file_path):
    """
    Decompresses a single .wrpl file.
    """
    with open(file_path, 'rb') as f:
        data = f.read()

    decompressed = bytearray(data)

    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        zstd_magic = b'\x28\xb5\x2f\xfd'
        for m in re.finditer(re.escape(zstd_magic), data):
            try:
                decomp = dctx.decompress(data[m.start():], max_output_size=15 * 1024 * 1024)
                decompressed.extend(decomp)
            except Exception:
                pass
    except ImportError:
        pass

    return len(data), bytes(decompressed)


def find_source_and_parse():
    id_to_display = load_german_json("german.json")
    files = sorted([f for f in os.listdir('.') if f.lower().endswith('.wrpl')])

    if not files:
        print("[!] No .wrpl files found in current directory.")
        return

    print("Scanning replay files individually to pinpoint the exact source file...\n")

    source_filename = None
    source_raw_size = 0
    parsed_players = []

    for fname in files:
        raw_size, payload = decompress_single_file(fname)

        # Search for match summary anchor in this specific file
        anchor_pos = payload.find(b"mati_gamming")

        if anchor_pos != -1:
            source_filename = fname
            source_raw_size = raw_size
            print(f"[+] Found Match Summary Array inside: '{fname}' (Offset: {hex(anchor_pos)})\n")

            # Extract 1200-byte snippet around summary block
            snippet = payload[max(0, anchor_pos - 100): min(len(payload), anchor_pos + 1100)]
            raw_strings = [s.decode('utf-8', errors='ignore') for s in re.findall(b'[A-Za-z0-9_\\-\\./]{3,}', snippet)]

            # Extract players in order
            ordered_players = []
            for s in raw_strings:
                if s in NAME_VARIANTS:
                    mapped = NAME_VARIANTS[s]
                    if mapped not in ordered_players:
                        ordered_players.append(mapped)

            # Extract vehicles in order
            wt_prefixes = ('germ_', 'il_', 'us_', 'ussr_', 'g_91', 'hunter_', 'f_4c', 'yak_')
            ordered_vehicles = []
            for s in raw_strings:
                if s in id_to_display or any(s.startswith(p) for p in wt_prefixes):
                    if not any(x in s for x in ['_streak', '_m82', 'camo', 'aim_9', 'lau_3a']):
                        if s not in ordered_vehicles:
                            ordered_vehicles.append(s)

            for i in range(min(len(ordered_players), len(ordered_vehicles))):
                p_name = ordered_players[i]
                v_id = ordered_vehicles[i]
                v_display = id_to_display.get(v_id, v_id)

                parsed_players.append({
                    "player_name": p_name,
                    "vehicle_id": v_id,
                    "vehicle_name": v_display
                })

            # Stop scanning once source file is found
            break

    if not source_filename:
        print("[!] Match summary array anchor not found in any file.")
        return

    total_folder_size = sum(os.path.getsize(f) for f in files)
    savings = round((1 - (source_raw_size / total_folder_size)) * 100, 1)

    result = {
        "source_file": source_filename,
        "source_file_size_kb": round(source_raw_size / 1024, 2),
        "num_players": len(parsed_players),
        "players": parsed_players
    }

    print("==========================================")
    print("PARSED MATCH RESULT")
    print("==========================================")
    print(json.dumps(result, indent=4))

    print("\n==========================================")
    print("SOURCE FILE PINPOINTED")
    print("==========================================")
    print(f"The player lineup and vehicles come from: {source_filename}")
    print(f"  - Size of {source_filename}: {round(source_raw_size / 1024, 2)} KB")
    print(f"  - Total Replay Folder Size: {round(total_folder_size / 1024, 2)} KB")
    print(f"  - Download Overhead Savings: {savings}% !")


if __name__ == "__main__":
    find_source_and_parse()