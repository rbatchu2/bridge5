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


def scan_blocks(chain: str, contract_info) -> int:
    if chain not in ('source', 'destination'):
        raise ValueError("chain must be 'source' or 'destination'")

    print(f"\n--- Scanning {chain} chain for events ---")
    w3_src = connect_to('source')
    w3_dst = connect_to('destination')

    # load ABIs & addresses
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

    # pick chain/contract/event
    if chain == 'source':
        w3_cur, contract, event_name = w3_src, src_contract, 'Deposit'
    else:
        w3_cur, contract, event_name = w3_dst, dst_contract, 'Unwrap'

    Event = getattr(contract.events, event_name)
    latest = w3_cur.eth.block_number
    start  = max(0, latest - BLOCKS_TO_SCAN)
    print(f"> Blocks {start} → {latest}")

    # fetch logs
    logs = []
    if chain == 'destination':
        # batch one block at a time to avoid RPC limits
        for b in range(start, latest + 1):
            try:
                batch = Event.get_logs(from_block=b, to_block=b)
                if batch:
                    print(f"  [block {b}] {len(batch)} event(s)")
                    logs.extend(batch)
            except Exception as e:
                print(f"  Warning: could not fetch block {b}: {e}")
    else:
        # source is small enough to pull in one go
        try:
            logs = Event.get_logs(from_block=start, to_block=latest)
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {event_name} logs: {e}")

    print(f"> Total {len(logs)} {event_name} event(s) found")
    processed = 0
    warden_addr = w3_src.to_checksum_address(WARDEN_ADDRESS_HEX)

    for ev in logs:
        print(f"\nEvent in tx {ev.transactionHash.hex()} @ block {ev.blockNumber}")
        args = ev.args

        # debug: show exactly what keys we have
        print("  Raw args keys:", list(args.keys()))

        # token is usually called 'token'
        token = args.get('token')
        # try to find the user field under various names
        user = None
        for field in ('user','from','to','sender','recipient'):
            if field in args:
                user = args[field]
                break

        if user is None:
            print("  ERROR: couldn't find a user field—skipping this event.")
            continue

        amount = args.get('amount')
        nonce  = args.get('nonce')

        # decide wrap vs withdraw
        if event_name == 'Deposit':
            tgt_w3, tgt_contract, fn, action = w3_dst, dst_contract, dst_contract.functions.wrap, 'wrap'
            fn_args = (token, user, amount, nonce)
        else:
            tgt_w3, tgt_contract, fn, action = w3_src, src_contract, src_contract.functions.withdraw, 'withdraw'
            fn_args = (token, user, amount, nonce)

        try:
            tx = fn(*fn_args).build_transaction({
                'from':     warden_addr,
                'nonce':    tgt_w3.eth.get_transaction_count(warden_addr),
                'chainId':  tgt_w3.eth.chain_id,
                'gas':      2_000_000,
                'gasPrice': tgt_w3.eth.gas_price
            })
            signed = tgt_w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            txh = tgt_w3.eth.send_raw_transaction(signed.raw_transaction)
            print(f"  Sent {action} → {txh.hex()}")
            processed += 1

        except ContractLogicError as cle:
            print(f"  Contract reverted on {action}: {cle}")
        except Exception as e:
            print(f"  Failed to send {action}: {e}")

    print(f"\n--- Done. Processed {processed} event(s) on {chain}. ---")
    return processed