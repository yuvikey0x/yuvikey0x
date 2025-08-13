import csv
import json
import os
import re

# === 1. Baca data dari CSV ===
csv_data = []
if os.path.exists("data.csv"):
    with open("data.csv", newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for i, row in enumerate(reader, start=1):
            try:
                # Ambil FID asli
                fid_original = row.get("fid", "").strip()

                # Hapus semua karakter non-angka
                fid_clean = re.sub(r"\D", "", fid_original)
                fid_value = int(fid_clean) if fid_clean else None

                print(f"[CSV] Baris {i}: FID asli: {fid_original!r} -> FID bersih: {fid_value}")

                csv_data.append({
                    "private_key": row.get("private_key", "").strip(),
                    "wallet_address": row.get("wallet_address", "").strip(),
                    "fid": fid_value,
                    "username": row.get("username", "").strip()
                })
            except Exception as e:
                print(f"[WARNING] Gagal memproses baris {i} CSV: {e}")
else:
    print("[WARNING] File data.csv tidak ditemukan!")

# === 2. Baca data dari JSON lama ===
if os.path.exists("data.json"):
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            json_data = json.load(f)
        if not isinstance(json_data, list):
            raise ValueError("Format JSON tidak berupa list")
    except Exception as e:
        print(f"[WARNING] Gagal membaca data.json: {e}")
        json_data = []
else:
