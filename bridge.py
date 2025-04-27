import sys
import json
from pathlib import Path
from datetime import datetime
import pandas as pd
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware


def connect_to(chain: str) -> Web3:
    """
    Connect to the appropriate RPC endpoint for 'source' (Avalanche) or 'destination' (BSC).
    """
    if chain == 'source':
        rpc_url = "https://api.avax-test.network/ext/bc/C/rpc"
    elif chain == 'destination':
        rpc_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
    else:
        raise ValueError(f"Unknown chain '{chain}'. Use 'source' or 'destination'.")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # inject POA compatibility middleware if needed
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain: str, contract_info_path: str) -> dict:
    """
    Load contract address and ABI from a JSON file.
    Expected format:
      {
        "source": { "address": "0x...", "abi": [ ... ] },
        "destination": { "address": "0x...", "abi": [ ... ] }
      }
    """
    try:
        with open(contract_info_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read contract info file: {e}")

    if chain not in data:
        raise KeyError(f"'{chain}' not found in {contract_info_path}")
    return data[chain]


def scan_blocks(chain: str, contract_info_path: str = "contract_info.json") -> None:
    """
    Scan the last 5 blocks for Deposit (on source) or Unwrap (on destination) events,
    and save any found to a CSV file.
    """
    info = get_contract_info(chain, contract_info_path)
    address = info["address"]
    abi = info["abi"]

    # connect and prepare contract
    w3 = connect_to(chain)
    checksum = Web3.to_checksum_address(address)  # <-- Web3 class, not instance
    contract = w3.eth.contract(address=checksum, abi=abi)

    # choose event
    event_name = "Deposit" if chain == "source" else "Unwrap"
    Event = getattr(contract.events, event_name)

    # determine block range (last 5 blocks)
    latest = w3.eth.block_number
    start = max(latest - 4, 0)
    end = latest
    print(f"Scanning {event_name} on {chain} from blocks {start} to {end}...")

    # fetch logs
    try:
        entries = Event.get_logs(fromBlock=start, toBlock=end)
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return

    if not entries:
        print("No events found.")
        return

    # parse events
    rows = []
    for ev in entries:
        blk = ev.blockNumber
        args = ev.args
        timestamp = w3.eth.get_block(blk)["timestamp"]

        # Safely get attributes to avoid crashing if missing
        row = {
            "block": blk,
            "timestamp": datetime.utcfromtimestamp(timestamp).isoformat(),
            "transaction": ev.transactionHash.hex(),
        }
        for field in ["token", "recipient", "amount"]:
            if hasattr(args, field):
                row[field] = getattr(args, field)
            else:
                row[field] = None  # fill missing fields with None

        rows.append(row)

    # save to CSV
    df = pd.DataFrame(rows)
    filename = Path(f"{chain}_{event_name.lower()}_events.csv")
    mode = "a" if filename.exists() else "w"
    header = not filename.exists()

    df.to_csv(filename, mode=mode, header=header, index=False)

    print(f"Saved {len(rows)} '{event_name}' events to {filename}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bridge_listener.py [source|destination]")
        sys.exit(1)

    chain = sys.argv[1].lower()
    if chain not in ("source", "destination"):
        print("Chain must be 'source' or 'destination'")
        sys.exit(1)

    scan_blocks(chain)