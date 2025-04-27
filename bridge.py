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
    with open(contract_info) as f:
        info = json.load(f)
    if chain not in info:
        raise KeyError(f"{chain!r} not in {contract_info}")
    addr = info[chain]["address"]
    abi  = info[chain]["abi"]

    if chain == "source":
        rpc = "https://api.avax-test.network/ext/bc/C/rpc"
    else:
        rpc = "https://data-seed-prebsc-1-s1.binance.org:8545/"
    w3 = Web3(Web3.HTTPProvider(rpc))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(addr),
        abi=abi
    )

    event_name = "Deposit" if chain == "source" else "Unwrap"
    Event = getattr(contract.events, event_name)

    latest      = w3.eth.block_number
    start_block = max(latest - 5 + 1, 0)
    end_block   = latest
    print(f"Scanning {event_name} on {chain} from {start_block}→{end_block}")

    try:
        entries = Event().get_logs({
        "from_block": start_block,
        "to_block":   end_block
    })
    except Exception:
        entries = []
        for b in range(start_block, end_block + 1):
            try:
                filt = Event.createFilter(fromBlock=b, toBlock=b)
                entries.extend(filt.get_all_entries())
            except:
                continue

    rows = []
    for ev in entries:
        blk  = ev.blockNumber
        args = ev.args
        ts   = w3.eth.get_block(blk)["timestamp"]
        rows.append({
            "block":         blk,
            "token":         args.get("token"),
            "recipient":     args.get("recipient"),
            "amount":        args.get("amount"),
            "timestamp":     datetime.utcfromtimestamp(ts).isoformat(),
            "transaction":   ev.transactionHash.hex()
        })

    if not rows:
        print("No events found.")
        return

    df = pd.DataFrame(rows)
    if eventfile is None:
        eventfile = f"{chain}_{event_name.lower()}_events.csv"
    mode   = "a" if Path(eventfile).exists() else "w"
    header = not Path(eventfile).exists()
    df.to_csv(eventfile, mode=mode, header=header, index=False)

    print(f"Saved {len(rows)} {event_name} events to {eventfile}")