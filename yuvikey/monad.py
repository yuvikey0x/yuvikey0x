import requests
from datetime import datetime, timezone
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3
import os
import json
import random
import time
import threading

Account.enable_unaudited_hdwallet_features()

# === Konstanta dan Endpoint ===
DOMAIN = "faucet-miniapp.monad.xyz"
BASE_URL = f"https://{DOMAIN}"
CHAIN_ID = 10
TARGET_ADDRESS = "0x4D6bE2793546A8306525aEe8A41aC290fecC4ada"

# Data jaringan Monad Testnet (dari foto)
RPC_URL = "https://rpc.ankr.com/monad_testnet"
CHAIN_ID_MONAD = 10143
EXPLORER_URL = "https://testnet.monadexplorer.com"
SYMBOL_MONAD = "MON"

GET_NONCE_ENDPOINT = f"{BASE_URL}/api/auth"
POST_AUTH_ENDPOINT = f"{BASE_URL}/api/auth"
POST_CLAIM_ENDPOINT = f"{BASE_URL}/api/claim"
PROXY_CHECK_URL = "http://httpbin.org/ip"


# === Konfigurasi ===
MAX_ATTEMPTS = 2
ACCOUNTS_PER_BATCH = 5
BALANCE_THRESHOLD = 1.0  # minimal MONAD untuk melakukan transfer
TRANSFER_BUFFER = 0.0001  # sisakan ini untuk keamanan setelah perhitungan gas
lock = threading.Lock()

w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Daftar akun yang eligible untuk transfer batch kedua
eligible_wallets = []

# === Loader Akun & Proxy ===
def load_accounts_from_json(json_file="data.json"):
    if not os.path.exists(json_file):
        print(f"❌ File `{json_file}` tidak ditemukan.")
        return []
    with open(json_file, "r") as f:
        data = json.load(f)
        return [
            {
                "wallet_address": acc["wallet_address"].strip(),
                "private_key": acc["private_key"].strip(),
                "fid": int(acc["fid"])
            }
            for acc in data
            if all(k in acc for k in ["wallet_address", "private_key", "fid"]) and acc["fid"]
        ]


def load_proxies(proxy_file="proxy.txt"):
    if not os.path.exists(proxy_file):
        print(f"❌ File `{proxy_file}` tidak ditemukan.")
        return []
    with open(proxy_file, "r") as f:
        return [{'http': line.strip(), 'https': line.strip()} for line in f if line.strip()]


def get_external_ip(proxy):
    try:
        res = requests.get(PROXY_CHECK_URL, proxies=proxy, timeout=10)
        return res.json().get("origin")
    except Exception:
        return None

# === Saldo & Kirim MONAD ===
def get_monad_balance_rpc(wallet_address):
    """Ambil saldo via RPC (returns float MONAD)"""
    try:
        # pastikan address checksum
        addr = Web3.to_checksum_address(wallet_address)
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [addr, "latest"],
            "id": 1
        }
        res = requests.post(RPC_URL, json=payload, timeout=20)
        result = res.json().get("result")
        if result:
            balance_wei = int(result, 16)
            balance_eth = balance_wei / (10 ** 18)
            return round(balance_eth, 12)
    except Exception as e:
        print(f"❌ Gagal ambil saldo RPC untuk {wallet_address}: {e}")
    return None


def estimate_gas_fee():
    """Estimasi biaya gas untuk transfer sederhana (wei)."""
    try:
        gas_price = w3.eth.gas_price
        gas_limit = 21000
        return gas_price * gas_limit
    except Exception as e:
        print(f"❌ Gagal ambil gas price: {e}")
        return None


def send_monad(private_key, from_address, to_address, amount):
    """Kirim amount (dalam MONAD, float). Fungsi akan sign & broadcast tx."""
    try:
        nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(from_address))
        gas_price = w3.eth.gas_price
        gas_limit = 21000

        value = w3.to_wei(amount, 'ether')

        tx = {
            "nonce": nonce,
            "to": Web3.to_checksum_address(to_address),
            "value": value,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "chainId": CHAIN_ID_MONAD
        }

        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)
        if not raw_tx:
            raise ValueError("Raw transaction tidak ditemukan setelah sign.")

        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        return w3.to_hex(tx_hash)
    except Exception as e:
        print(f"❌ Gagal mengirim MONAD dari {from_address}: {e}")
        return None

# === Autentikasi & Klaim ===
def fetch_nonce(fid, proxy):
    try:
        res = requests.get(f"{GET_NONCE_ENDPOINT}?fid={fid}", proxies=proxy, timeout=15)
        return res.json().get("nonce")
    except Exception:
        return None


def build_siwe_message(wallet, fid, nonce, issued_at):
    return (
        f"{DOMAIN} wants you to sign in with your Ethereum account:\n"
        f"{wallet}\n\n"
        f"Farcaster Auth\n\n"
        f"URI: https://{DOMAIN}/\n"
        f"Version: 1\n"
        f"Chain ID: {CHAIN_ID}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        f"Resources:\n"
        f"- farcaster://fid/{fid}"
    )


def sign_message(message, pk):
    encoded = encode_defunct(text=message)
    signed = Account.sign_message(encoded, pk)
    return '0x' + signed.signature.hex()


def authenticate(wallet_address, fid, private_key, proxy):
    nonce = fetch_nonce(fid, proxy)
    if not nonce:
        return None
    issued_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    message = build_siwe_message(wallet_address, fid, nonce, issued_at)
    signature = sign_message(message, private_key)
    payload = {
        "message": message,
        "signature": signature,
        "nonce": nonce,
        "fid": fid
    }
    headers = {"Content-Type": "application/json"}
    try:
        res = requests.post(POST_AUTH_ENDPOINT, headers=headers, json=payload, proxies=proxy, timeout=30)
        return res.json().get("token")
    except Exception:
        return None


def claim_faucet(token, wallet_address, proxy):
    payload = {"address": wallet_address}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    try:
        res = requests.post(POST_CLAIM_ENDPOINT, headers=headers, json=payload, proxies=proxy, timeout=30)
        result = res.json()
        # API mungkin mengembalikan {"txHash": ...} saat sudah diklaim atau berhasil
        if isinstance(result, dict) and "txHash" in result:
            return "already_claimed"
        # Jika server mengembalikan success flag, coba mendeteksi
        if isinstance(result, dict) and result.get("success") is True:
            return "claimed"
        # fallback: jika tidak error, anggap claimed
        return "claimed"
    except Exception:
        return "failed"

# === Proses Klaim (fase 1) ===
def run_account_claim(acc, proxies):
    wallet = acc["wallet_address"]
    fid = acc["fid"]
    pk = acc["private_key"]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        proxy = random.choice(proxies)
        ip = get_external_ip(proxy)
        if not ip:
            continue

        try:
            signer = Account.from_key(pk)
            if signer.address.lower() != wallet.lower():
                with lock:
                    print(f"❌ {wallet} - Private key tidak cocok.")
                return
        except Exception:
            with lock:
                print(f"❌ {wallet} - Private key tidak valid.")
            return

        token = authenticate(wallet, fid, pk, proxy)
        if not token:
            with lock:
                print(f"⚠️ {wallet} - Gagal autentikasi (percobaan {attempt}).")
            continue

        result = claim_faucet(token, wallet, proxy)

        with lock:
            if result == "claimed":
                print(f"🎉 {wallet} - Klaim sukses.")
            elif result == "already_claimed":
                print(f"✅ {wallet} - Sudah diklaim sebelumnya.")
            else:
                print(f"⚠️ {wallet} - Gagal klaim (percobaan {attempt}).")

        if result in ["claimed", "already_claimed"]:
            # tambahkan ke daftar eligible untuk phase transfer
            with lock:
                eligible_wallets.append({"wallet_address": wallet, "private_key": pk})
            return

        time.sleep(1)

    with lock:
        print(f"❌ {wallet} - Gagal klaim setelah {MAX_ATTEMPTS} percobaan.")


# === Proses Transfer Batch (fase 2) ===
def process_transfers(batch_size=5, delay_between=0.5):
    print("\n🚀 Memulai batch transfer MONAD...")
    # proses dalam batch agar tidak overload RPC
    for i in range(0, len(eligible_wallets), batch_size):
        batch = eligible_wallets[i:i+batch_size]
        threads = []

        def transfer_worker(acc):
            wallet = acc["wallet_address"]
            pk = acc["private_key"]
            balance = get_monad_balance_rpc(wallet)
            if balance is None:
                print(f"⏭️ {wallet} - Tidak dapat membaca saldo, skip.")
                return

            # ambil estimasi gas fee (wei) lalu konversi ke MONAD
            gas_fee_wei = estimate_gas_fee()
            if gas_fee_wei is None:
                print(f"⚠️ {wallet} - Gagal estimasi gas, skip transfer.")
                return
            gas_fee_monad = gas_fee_wei / (10 ** 18)

            # hitung amount yang akan dikirim (sisakan buffer dan biaya gas)
            amount_to_send = balance - gas_fee_monad - TRANSFER_BUFFER
            # Pastikan amount_to_send positif dan lebih besar dari threshold kecil
            if amount_to_send <= 0:
                print(f"⏩ {wallet} - Saldo {balance} MONAD tidak cukup setelah biaya gas ({gas_fee_monad}) dan buffer.")
                return

            # Kirim
            print(f"💸 {wallet} - Mengirim {amount_to_send:.6f} MONAD (Saldo: {balance}) ke {TARGET_ADDRESS}...")
            tx_hash = send_monad(pk, wallet, TARGET_ADDRESS, amount_to_send)
            if tx_hash:
                print(f"✅ {wallet} - Transfer sukses! TX: {tx_hash}")
            else:
                print(f"⚠️ {wallet} - Transfer gagal.")

        for acc in batch:
            t = threading.Thread(target=transfer_worker, args=(acc,))
            t.start()
            threads.append(t)
            time.sleep(delay_between)

        for t in threads:
            t.join()

    print("\n✅ Semua transfer batch selesai.")


# === Main Loop ===
def main_loop():
    try:
        while True:
            all_accounts = load_accounts_from_json()
            proxies = load_proxies()
            if not all_accounts or not proxies:
                print("❌ Tidak ada akun atau proxy.")
                return

            # kosongkan eligible list tiap siklus
            eligible_wallets.clear()

            batch_num = 1
            total = len(all_accounts)
            print(f"🚀 Menjalankan total {total} akun dalam batch {ACCOUNTS_PER_BATCH}-thread...\n")

            for i in range(0, total, ACCOUNTS_PER_BATCH):
                batch = all_accounts[i:i + ACCOUNTS_PER_BATCH]
                print(f"\n📦 Batch klaim {batch_num}: {len(batch)} akun")
                threads = []

                for acc in batch:
                    t = threading.Thread(target=run_account_claim, args=(acc, proxies))
                    t.start()
                    threads.append(t)
                    time.sleep(0.3)

                for t in threads:
                    t.join()
                batch_num += 1

            print("\n✅ Semua akun selesai klaim fase.")

            # Phase 2: lakukan transfer untuk yang eligible
            if eligible_wallets:
                process_transfers(batch_size=ACCOUNTS_PER_BATCH, delay_between=0.2)
            else:
                print("⏭️ Tidak ada akun yang eligible transfer pada siklus ini.")

            print("\n⏳ Menunggu 1 jam sebelum siklus berikutnya...\n")
            time.sleep(60 * 60)

    except KeyboardInterrupt:
        print("\n🛑 Program dihentikan oleh pengguna (Ctrl+C).\n")


if __name__ == "__main__":
    main_loop()
