import csv
import json
import os
import re

# === 1. Baca data dari CSV ===
csv_data = []
with open("data.csv", newline="", encoding="utf-8") as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        fid_original = row["fid"]
        
        # Hapus semua karakter non-angka
        fid_clean = re.sub(r"\D", "", fid_original)
        fid_value = int(fid_clean) if fid_clean else None

        # Log perubahan
        print(f"FID asli: {fid_original!r} -> FID bersih: {fid_value}")

        csv_data.append({
            "private_key": row["private_key"],
            "wallet_address": row["wallet_address"],
            "fid": fid_value,
            "username": row["username"]
        })

# === 2. Baca data dari JSON lama ===
if os.path.exists("data.json"):
    with open("data.json", "r", encoding="utf-8") as f:
        json_data = json.load(f)
else:
    json_data = []

# === 3. Gabungkan dan hapus duplikat berdasarkan wallet_address ===
combined = json_data + csv_data
unique_data = {}
for entry in combined:
    unique_data[entry["wallet_address"]] = entry

# === 4. Urutkan berdasarkan fid (None dianggap terbesar) ===
sorted_data = sorted(
    unique_data.values(),
    key=lambda x: (x["fid"] is None, x["fid"] if x["fid"] is not None else 0)
)

# === 5. Simpan ke file baru ===
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(sorted_data, f, indent=4)

print("\n✅ File 'data.json' berhasil dibuat dan disortir.")
