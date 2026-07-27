import os
import re
import sys


def inspect_replay_file(file_path):
    """
    Parses a single .wrpl file, attempts Zstd decompression,
    and returns a set of detected vehicle identifiers.
    """
    if not os.path.exists(file_path):
        return set()

    with open(file_path, 'rb') as f:
        data = f.read()

    # Search for Zstandard compression magic bytes (28 B5 2F FD)
    zstd_magic = b'\x28\xb5\x2f\xfd'
    zstd_offsets = [m.start() for m in re.finditer(re.escape(zstd_magic), data)]

    decompressed_buffers = []

    # Attempt Payload Decompression
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()

        for offset in zstd_offsets:
            try:
                decomp = dctx.decompress(data[offset:], max_output_size=10 * 1024 * 1024)
                decompressed_buffers.append(decomp)
            except Exception:
                pass
    except ImportError:
        pass

    # Scan combined raw and decompressed data for vehicle strings
    combined_data = data + b''.join(decompressed_buffers)

    # War Thunder internal vehicle identifiers use country prefixes
    wt_prefixes = (
        b'us_', b'germ_', b'ussr_', b'uk_', b'jp_',
        b'cn_', b'it_', b'fr_', b'se_', b'il_'
    )

    all_strings = re.findall(b'[A-Za-z0-9_\\-\\./]{4,}', combined_data)

    detected_vehicles = set()
    for s in all_strings:
        if any(s.startswith(p) for p in wt_prefixes):
            detected_vehicles.add(s.decode('utf-8', errors='ignore'))

    return detected_vehicles


def process_directory(folder_path):
    """
    Finds and parses all .wrpl files in the target directory.
    """
    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a valid directory.")
        return

    print(f"Scanning directory: {folder_path}\n")

    # Match all .wrpl files (e.g., 0000.wrpl, 0001.wrpl ... 0005.wrpl)
    files = sorted([
        f for f in os.listdir(folder_path)
        if f.lower().endswith('.wrpl')
    ])

    if not files:
        print("No .wrpl files found in this directory.")
        return

    all_detected_vehicles = set()

    for filename in files:
        file_path = os.path.join(folder_path, filename)
        print(f"--- Parsing {filename} ---")

        vehicles = inspect_replay_file(file_path)

        if vehicles:
            print(f"Found {len(vehicles)} vehicle string(s):")
            for v in sorted(vehicles):
                print(f"  - {v}")
            all_detected_vehicles.update(vehicles)
        else:
            print("No vehicle strings detected in this segment.")
        print()

    print("==========================================")
    print(f"TOTAL COMBINED UNIQUE VEHICLES ({len(all_detected_vehicles)}):")
    print("==========================================")
    if all_detected_vehicles:
        for v in sorted(all_detected_vehicles):
            print(f"  - {v}")
    else:
        print("No vehicles found across all replay files.")


if __name__ == "__main__":
    # If a folder path is passed as an argument, use it;
    # otherwise default to the current project working directory
    if len(sys.argv) > 1:
        target_folder = sys.argv[1]
    else:
        target_folder = os.getcwd()

    process_directory(target_folder)