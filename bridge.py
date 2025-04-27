import sys
import json
from pathlib import Path
from datetime import datetime
# Removed pandas as it wasn't used
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.exceptions import ContractLogicError # Added for specific error handling

# --- Configuration ---
# Consider moving sensitive data like private keys to environment variables or a secure config file
PRIVATE_KEY = "0x5fd95ff938a7d2119549e6524e84213e7428cf9e07afc654f73cc1c81007a09b" # WARNING: Hardcoding private keys is insecure!
WARDEN_ADDRESS = Web3.to_checksum_address("0x271eB4B27Ac1D98c76b99aa4923A521d9e673061")
CONTRACT_INFO_PATH = "contract_info.json" # Default path for contract details
BLOCKS_TO_SCAN = 5 # Number of recent blocks to check

# --- RPC Endpoints ---
RPC_URLS = {
    'source': "https://api.avax-test.network/ext/bc/C/rpc", # Avalanche Fuji Testnet
    'destination': "https://data-seed-prebsc-1-s1.binance.org:8545/" # BSC Testnet
}

def connect_to(chain: str) -> Web3:
    """
    Connects to the RPC endpoint for the specified chain ('source' or 'destination').

    Args:
        chain: The name of the chain ('source' or 'destination').

    Returns:
        A Web3 instance connected to the chain.

    Raises:
        ValueError: If the chain name is invalid.
        ConnectionError: If connection to the RPC endpoint fails.
    """
    if chain not in RPC_URLS:
        raise ValueError(f"Unknown chain '{chain}'. Use 'source' or 'destination'.")

    rpc_url = RPC_URLS[chain]
    print(f"Connecting to {chain} chain at {rpc_url}...")
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        # Inject POA compatibility middleware (required for some chains like BSC, Polygon, Avax C-Chain)
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not w3.is_connected():
             raise ConnectionError(f"Failed to connect to {rpc_url}")
        print(f"Successfully connected to {chain}. Chain ID: {w3.eth.chain_id}")
        return w3
    except Exception as e:
        raise ConnectionError(f"Error connecting to {rpc_url}: {e}")


def get_contract_info(chain: str, contract_info_path: str = CONTRACT_INFO_PATH) -> dict:
    """
    Loads contract address and ABI from a JSON file for the specified chain.

    Args:
        chain: The name of the chain ('source' or 'destination').
        contract_info_path: Path to the JSON file containing contract details.
                            Expected format:
                            {
                              "source": { "address": "0x...", "abi": [ ... ] },
                              "destination": { "address": "0x...", "abi": [ ... ] }
                            }

    Returns:
        A dictionary containing the 'address' and 'abi' for the specified chain.

    Raises:
        FileNotFoundError: If the contract info file doesn't exist.
        RuntimeError: If the file cannot be read or parsed.
        KeyError: If the specified chain is not found in the JSON data.
    """
    try:
        with open(contract_info_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Contract info file not found: {contract_info_path}")
    except json.JSONDecodeError as e:
         raise RuntimeError(f"Failed to parse contract info file ({contract_info_path}): {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to read contract info file ({contract_info_path}): {e}")

    if chain not in data:
        raise KeyError(f"Chain '{chain}' not found in {contract_info_path}")
    if "address" not in data[chain] or "abi" not in data[chain]:
         raise KeyError(f"Contract info for '{chain}' in {contract_info_path} must contain 'address' and 'abi'.")

    return data[chain]


def scan_blocks(chain: str, contract_info: str = CONTRACT_INFO_PATH) -> int:
    if chain not in ['source', 'destination']:
        raise ValueError(f"Invalid chain: '{chain}'. Use 'source' or 'destination'.")

    print(f"\n--- Starting scan on '{chain}' chain ---")

    try:
        w3_source = connect_to('source')
        w3_destination = connect_to('destination')

        source_info = get_contract_info('source', contract_info)
        dest_info = get_contract_info('destination', contract_info)

        source_contract = w3_source.eth.contract(
            address=Web3.to_checksum_address(source_info['address']),
            abi=source_info['abi']
        )
        destination_contract = w3_destination.eth.contract(
            address=Web3.to_checksum_address(dest_info['address']),
            abi=dest_info['abi']
        )
    except (ConnectionError, FileNotFoundError, RuntimeError, KeyError) as e:
        print(f"Error during setup: {e}")
        raise

    try:
        if chain == 'source':
            latest_block = w3_source.eth.block_number
            start_block = max(0, latest_block - BLOCKS_TO_SCAN)
            print(f"Scanning source chain blocks from {start_block} to {latest_block}")
        else: # destination
            latest_block = w3_destination.eth.block_number
            start_block = max(0, latest_block - BLOCKS_TO_SCAN)
            print(f"Scanning destination chain blocks from {start_block} to {latest_block}")
    except Exception as e:
        print(f"Error getting latest block number: {e}")
        raise

    events_processed = 0

    # --- Event Scanning and Processing ---
    try:
        if chain == 'source':
            # Create a filter for Deposit events
            deposit_event_filter = source_contract.events.Deposit.create_filter(
                fromBlock=start_block,
                toBlock=latest_block,
                argument_filters={} # No specific argument filtering
            )

            # *** FIX: Use get_all_entries() to fetch events from the filter ***
            deposit_events = deposit_event_filter.get_all_entries()
            print(f"Found {len(deposit_events)} potential Deposit events in the block range.")

            for event in deposit_events:
                print(f"\nProcessing Deposit event found in tx {event.transactionHash.hex()} (block {event.blockNumber})")
                args = event.args
                token_address = args.token
                user = args.user
                amount = args.amount
                nonce = args.nonce # This nonce comes from the event data

                print(f"  Token: {token_address}, User: {user}, Amount: {amount}, Nonce: {nonce}")

                # Build and send 'wrap' transaction on the destination chain
                print("  Building 'wrap' transaction for destination chain...")
                try:
                    # Get the nonce for the warden account on the destination chain
                    warden_nonce_dest = w3_destination.eth.get_transaction_count(WARDEN_ADDRESS)

                    wrap_tx = destination_contract.functions.wrap(
                        token_address,
                        user,
                        amount,
                        nonce # Pass the nonce from the event
                    ).build_transaction({
                        'from': WARDEN_ADDRESS,
                        'gas': 2000000, # Consider estimating gas: w3_destination.eth.estimate_gas({...})
                        'gasPrice': w3_destination.eth.gas_price,
                        'nonce': warden_nonce_dest,
                        'chainId': w3_destination.eth.chain_id
                    })

                    signed_tx = w3_destination.eth.account.sign_transaction(wrap_tx, PRIVATE_KEY)
                    tx_hash = w3_destination.eth.send_raw_transaction(signed_tx.rawTransaction)
                    print(f"  Sent 'wrap' transaction to destination chain: {tx_hash.hex()}")
                    # Optional: Wait for transaction receipt
                    # receipt = w3_destination.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                    # print(f"  'wrap' transaction confirmed. Status: {receipt.status}")
                    events_processed += 1
                except ContractLogicError as cle:
                    print(f"  ERROR: Contract logic error sending 'wrap' tx: {cle}")
                except Exception as e:
                    print(f"  ERROR: Failed to send 'wrap' transaction: {e}")


        elif chain == 'destination':
            # Fetch Unwrap events using get_logs (alternative to create_filter)
            unwrap_events = destination_contract.events.Unwrap.get_logs(
                fromBlock=start_block,
                toBlock=latest_block
            )
            print(f"Found {len(unwrap_events)} potential Unwrap events in the block range.")

            for event in unwrap_events:
                print(f"\nProcessing Unwrap event found in tx {event.transactionHash.hex()} (block {event.blockNumber})")
                args = event.args
                token_address = args.token
                user = args.user
                amount = args.amount
                nonce = args.nonce # This nonce comes from the event data

                print(f"  Token: {token_address}, User: {user}, Amount: {amount}, Nonce: {nonce}")

                # Build and send 'withdraw' transaction on the source chain
                print("  Building 'withdraw' transaction for source chain...")
                try:
                     # Get the nonce for the warden account on the source chain
                    warden_nonce_source = w3_source.eth.get_transaction_count(WARDEN_ADDRESS)

                    withdraw_tx = source_contract.functions.withdraw(
                        token_address,
                        user,
                        amount,
                        nonce # Pass the nonce from the event
                    ).build_transaction({
                        'from': WARDEN_ADDRESS,
                        'gas': 2000000, # Consider estimating gas
                        'gasPrice': w3_source.eth.gas_price,
                        'nonce': warden_nonce_source,
                        'chainId': w3_source.eth.chain_id
                    })

                    signed_tx = w3_source.eth.account.sign_transaction(withdraw_tx, PRIVATE_KEY)
                    tx_hash = w3_source.eth.send_raw_transaction(signed_tx.rawTransaction)
                    print(f"  Sent 'withdraw' transaction to source chain: {tx_hash.hex()}")
                    # Optional: Wait for transaction receipt
                    # receipt = w3_source.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                    # print(f"  'withdraw' transaction confirmed. Status: {receipt.status}")
                    events_processed += 1
                except ContractLogicError as cle:
                    print(f"  ERROR: Contract logic error sending 'withdraw' tx: {cle}")
                except Exception as e:
                    print(f"  ERROR: Failed to send 'withdraw' transaction: {e}")

    except Exception as e:
        print(f"An unexpected error occurred during event processing: {e}")
        # Decide if you want to raise or just log and continue/return
        raise

    print(f"\n--- Scan finished on '{chain}' chain. Processed {events_processed} events. ---")
    return events_processed

# --- Example Usage ---
if __name__ == "__main__":
    # Make sure contract_info.json exists and is correctly formatted
    # Example:
    # {
    #   "source": {
    #     "address": "0xYourSourceContractAddress",
    #     "abi": [ ... ABI JSON ... ]
    #   },
    #   "destination": {
    #     "address": "0xYourDestinationContractAddress",
    #     "abi": [ ... ABI JSON ... ]
    #   }
    # }

    # WARNING: Ensure the PRIVATE_KEY corresponds to the WARDEN_ADDRESS
    # and has funds on both testnets to pay for gas.

    try:
        print("Scanning source chain (Avalanche Testnet) for Deposit events...")
        processed_source = scan_blocks('source')
        print(f"Completed source scan. Processed {processed_source} events.")

        print("\nScanning destination chain (BSC Testnet) for Unwrap events...")
        processed_dest = scan_blocks('destination')
        print(f"Completed destination scan. Processed {processed_dest} events.")

    except (ValueError, ConnectionError, FileNotFoundError, RuntimeError, KeyError, ContractLogicError) as e:
         print(f"\nSCRIPT FAILED: {e}")
         sys.exit(1) # Exit with error code
    except Exception as e:
         print(f"\nUNEXPECTED SCRIPT FAILURE: {e}")
         import traceback
         traceback.print_exc() # Print full traceback for unexpected errors
         sys.exit(1)

    print("\nScript finished successfully.")
