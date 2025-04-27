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
    if chain not in ['source','destination']:
        print(f"Invalid chain: {chain}")
        return 0
    
    with open(contract_info, "r") as f:
        info = json.load(f)
    
    w3_source = connect_to('source')
    w3_destination = connect_to('destination')
    
    source_contract_address = Web3.to_checksum_address(info["source_contract_address"])
    source_contract = w3_source.eth.contract(
        address=source_contract_address,
        abi=info["source_contract_abi"]
    )
    
    destination_contract_address = Web3.to_checksum_address(info["destination_contract_address"])
    destination_contract = w3_destination.eth.contract(
        address=destination_contract_address,
        abi=info["destination_contract_abi"]
    )
    
    private_key = "0x5fd95ff938a7d2119549e6524e84213e7428cf9e07afc654f73cc1c81007a09b"
    warden_address = Web3.to_checksum_address(info["0x271eB4B27Ac1D98c76b99aa4923A521d9e673061"])
    
    source_latest_block = w3_source.eth.block_number
    destination_latest_block = w3_destination.eth.block_number
    
    blocks_to_scan = 5
    
    source_start_block = max(0, source_latest_block - blocks_to_scan)
    destination_start_block = max(0, destination_latest_block - blocks_to_scan)
    
    events_found = 0
    
    if chain == 'source':
        deposit_events = source_contract.events.Deposit.get_logs(
            fromBlock=source_start_block,
            toBlock=source_latest_block
        )
        
        for event in deposit_events:
            print(f"Found Deposit event: {event}")
            
            token_address = event.args.token
            user = event.args.user
            amount = event.args.amount
            nonce = event.args.nonce
            
            wrap_tx = destination_contract.functions.wrap(
                token_address,
                user,
                amount,
                nonce
            ).build_transaction({
                'from': warden_address,
                'gas': 2000000,
                'gasPrice': w3_destination.eth.gas_price,
                'nonce': w3_destination.eth.get_transaction_count(warden_address),
                'chainId': w3_destination.eth.chain_id
            })
            
            signed_tx = w3_destination.eth.account.sign_transaction(wrap_tx, private_key)
            tx_hash = w3_destination.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            print(f"Sent wrap transaction: {tx_hash.hex()}")
            events_found += 1
    
    elif chain == 'destination':
        unwrap_events = destination_contract.events.Unwrap.get_logs(
            fromBlock=destination_start_block,
            toBlock=destination_latest_block
        )
        
        for event in unwrap_events:
            print(f"Found Unwrap event: {event}")
            
            token_address = event.args.token
            user = event.args.user
            amount = event.args.amount
            nonce = event.args.nonce
            
            withdraw_tx = source_contract.functions.withdraw(
                token_address,
                user,
                amount,
                nonce
            ).build_transaction({
                'from': warden_address,
                'gas': 2000000,
                'gasPrice': w3_source.eth.gas_price,
                'nonce': w3_source.eth.get_transaction_count(warden_address),
                'chainId': w3_source.eth.chain_id
            })
            
            signed_tx = w3_source.eth.account.sign_transaction(withdraw_tx, private_key)
            tx_hash = w3_source.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            print(f"Sent withdraw transaction: {tx_hash.hex()}")
            events_found += 1
    
    return events_found
