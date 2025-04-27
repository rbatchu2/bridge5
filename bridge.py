import sys
import os
import json
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.exceptions import ContractLogicError, BlockNotFound

# --- Configuration ---
# It's safer to set PRIVATE_KEY in your environment:
PRIVATE_KEY       = os.getenv("PRIVATE_KEY", "0x5fd95ff938a7d2119549e6524e84213e7428cf9e07afc654f73cc1c81007a09b")
WARDEN_ADDRESS_HEX = "0x271eB4B27Ac1D98c76b99aa4923A521d9e673061"

CONTRACT_INFO_PATH = "contract_info.json"
BLOCKS_TO_SCAN     = 5

RPC_URLS = {
    'source':      "https://api.avax-test.network/ext/bc/C/rpc",
    'destination': "https://data-seed-prebsc-1-s1.binance.org:8545/"
}


def connect_to(chain: str) -> Web3:
    if chain not in RPC_URLS:
        raise ValueError(f"Unknown chain '{chain}'. Use 'source' or 'destination'.")

    rpc = RPC_URLS[chain]
    w3  = Web3(Web3.HTTPProvider(rpc))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to {rpc}")
    print(f"> Connected to {chain} (chainId={w3.eth.chain_id})")
    return w3


def get_contract_info(chain: str, path: str = CONTRACT_INFO_PATH) -> dict:
    try:
        data = json.load(open(path))
    except FileNotFoundError:
        raise FileNotFoundError(f"Cannot find {path}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Bad JSON in {path}: {e}")

    if chain not in data or 'address' not in data[chain] or 'abi' not in data[chain]:
        raise KeyError(f"'{chain}' must exist in {path} with 'address' and 'abi'")
    return data[chain]


def scan_blocks(chain: str) -> int:
    if chain not in ('source', 'destination'):
        raise ValueError("chain must be 'source' or 'destination'")

    print(f"\n--- Scanning {chain} chain for events ---")
    # 1) Connect to both chains
    w3_src = connect_to('source')
    w3_dst = connect_to('destination')

    # 2) Load contracts
    src_info = get_contract_info('source')
    dst_info = get_contract_info('destination')

    src_contract = w3_src.eth.contract(
        address=w3_src.to_checksum_address(src_info['address']),
        abi=src_info['abi']
    )
    dst_contract = w3_dst.eth.contract(
        address=w3_dst.to_checksum_address(dst_info['address']),
        abi=dst_info['abi']
    )

    # 3) Pick which chain/contract to scan
    if chain == 'source':
        w3_cur, contract, event_name = w3_src, src_contract, 'Deposit'
    else:
        w3_cur, contract, event_name = w3_dst, dst_contract, 'Unwrap'

    # 4) Determine block range
    latest = w3_cur.eth.block_number
    start  = max(0, latest - BLOCKS_TO_SCAN)
    print(f"> Blocks {start} → {latest}")

    # 5) Fetch logs via unified get_logs()
    Event = getattr(contract.events, event_name)
    try:
        logs = Event.get_logs(from_block=start, to_block=latest)
    except BlockNotFound:
        print("Warning: some blocks not found, continuing with what we have…")
        logs = []
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {event_name} logs: {e}")

    print(f"> Found {len(logs)} {event_name} event(s)")
    processed = 0

    # 6) Handle each event
    warden_addr = w3_src.to_checksum_address(WARDEN_ADDRESS_HEX)
    for ev in logs:
        print(f"\nEvent in tx {ev.transactionHash.hex()} @ block {ev.blockNumber}")
        try:
            args   = ev.args
            token  = args.token
            user   = args.user
            amount = args.amount
            nonce  = args.nonce
        except AttributeError as e:
            print("  Skipping—missing expected args:", e)
            continue

        # Decide wrap vs. withdraw
        if event_name == 'Deposit':
            target_w3, target_contract, fn = w3_dst, dst_contract, target_contract.functions.wrap
            action = 'wrap'
        else:
            target_w3, target_contract, fn = w3_src, src_contract, target_contract.functions.withdraw
            action = 'withdraw'

        # Build & send
        try:
            tx = fn(token, user, amount, nonce).build_transaction({
                'from':      warden_addr,
                'nonce':     target_w3.eth.get_transaction_count(warden_addr),
                'chainId':   target_w3.eth.chain_id,
                'gas':       2_000_000,
                'gasPrice':  target_w3.eth.gas_price
            })
            signed = target_w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            # ← key fix: in v6 it's .raw_transaction, not .rawTransaction 
            tx_hash = target_w3.eth.send_raw_transaction(signed.raw_transaction)
            print(f"  Sent {action} tx: {tx_hash.hex()}")
            processed += 1

        except ContractLogicError as cle:
            print("  Contract reverted:", cle)
        except Exception as e:
            print("  Failed to send tx:", e)

    print(f"\n--- Done. Processed {processed} event(s) on {chain}. ---")
    return processed


if __name__ == "__main__":
    try:
        src_count  = scan_blocks('source')
        dst_count  = scan_blocks('destination')
        print(f"\nAll done: source={src_count}, destination={dst_count}")

    except Exception as e:
        print("\n✖ ERROR:", e)
        sys.exit(1)

    print("\n✔ Script finished successfully.")
