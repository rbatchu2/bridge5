from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from pathlib import Path
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc" #AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is bsc
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/" #BSC testnet

    if chain in ['source','destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r')  as f:
            contracts = json.load(f)
    except Exception as e:
        print( f"Failed to read contract info\nPlease contact your instructor\n{e}" )
        return 0
    return contracts[chain]



def scan_blocks(chain, contract_info="contract_info.json"):
    """
        chain - (string) should be either "source" or "destination"
        Scan the last 5 blocks of the source and destination chains
        Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain
        When Deposit events are found on the source chain, call the 'wrap' function the destination chain
        When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain
    """
    info       = json.load(open(contract_info))
    addr       = info[chain]["address"]
    abi        = info[chain]["abi"]
    rpc        = (
        "https://api.avax-test.network/ext/bc/C/rpc"
        if chain == "source"
        else "https://data-seed-prebsc-1-s1.binance.org:8545/"
    )
    w3         = Web3(Web3.HTTPProvider(rpc))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    contract   = w3.eth.contract(address=w3.to_checksum_address(addr), abi=abi)
    event_name = "Deposit" if chain == "source" else "Unwrap"
    Event      = getattr(contract.events, event_name)

    latest     = w3.eth.block_number
    start      = max(latest - 5 + 1, 0)
    end        = latest
    print(f"Scanning {event_name} on {chain} from {start}→{end}")

    entries = Event().get_logs({
        "from_block": start,
        "to_block":   end,
    })

    if not entries:
        print("No events found.")
        return

    rows = []
    for ev in entries:
        blk  = ev.block_number
        args = ev.args
        ts   = w3.eth.get_block(blk)["timestamp"]
        rows.append({
            "block":       blk,
            "token":       args.token,
            "recipient":   args.recipient,
            "amount":      args.amount,
            "timestamp":   datetime.utcfromtimestamp(ts).isoformat(),
            "transaction": ev.transaction_hash.hex()
        })

    df = pd.DataFrame(rows)
    eventfile = f"{chain}_{event_name.lower()}_events.csv"
    mode      = "a" if Path(eventfile).exists() else "w"
    header    = not Path(eventfile).exists()
    df.to_csv(eventfile, mode=mode, header=header, index=False)

    print(f"Saved {len(rows)} {event_name} events to {eventfile}")