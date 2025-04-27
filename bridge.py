import sys
import json
from pathlib import Path
from datetime import datetime
# Removed pandas as it wasn't used
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.exceptions import ContractLogicError # Added for specific error handling
from web3.datastructures import AttributeDict # Import AttributeDict for type checking if needed

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
        KeyError: If the specified chain is not found in the JSON data or is missing keys.
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

    # Return the specific chain's info
    return data[chain]


# *** Reverted parameter names back to original: 'chain' and 'contract_info' ***
def scan_blocks(chain: str, contract_info: str = CONTRACT_INFO_PATH) -> int:
    """
    Scans recent blocks on the specified chain for Deposit (on source) or
    Unwrap (on destination) events. If found, triggers a corresponding
    transaction (wrap or withdraw) on the other chain using the warden account.

    Args:
        chain: The chain to scan for events ('source' or 'destination').
        contract_info: Path to the JSON file with contract details.

    Returns:
        The number of events found and processed.

    Raises:
        ValueError: If chain is invalid.
        ConnectionError: If unable to connect to either blockchain.
        FileNotFoundError, RuntimeError, KeyError: From get_contract_info.
        ContractLogicError: If a contract call reverts.
        Exception: For other unexpected errors during processing.
    """
    # Use the 'chain' parameter directly for validation
    if chain not in ['source', 'destination']:
        raise ValueError(f"Invalid chain: '{chain}'. Use 'source' or 'destination'.")

    # Use the 'chain' parameter in the print statement
    print(f"\n--- Starting scan on '{chain}' chain ---")

    # --- Setup Connections and Contracts ---
    try:
        w3_source = connect_to('source')
        w3_destination = connect_to('destination')

        # Use the 'contract_info' parameter path when calling get_contract_info
        source_details = get_contract_info('source', contract_info)
        dest_details = get_contract_info('destination', contract_info)

        source_contract = w3_source.eth.contract(
            address=Web3.to_checksum_address(source_details['address']),
            abi=source_details['abi']
        )
        destination_contract = w3_destination.eth.contract(
            address=Web3.to_checksum_address(dest_details['address']),
            abi=dest_details['abi']
        )
    except (ConnectionError, FileNotFoundError, RuntimeError, KeyError) as e:
        print(f"Error during setup: {e}")
        raise # Re-raise the exception after logging

    # --- Determine Block Range ---
    try:
        # Use the 'chain' parameter for logic
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
        # Use the 'chain' parameter for logic
        if chain == 'source':
            deposit_event_filter = source_contract.events.Deposit.create_filter(
                from_block=start_block,
                to_block=latest_block,
                argument_filters={}
            )

            deposit_events = deposit_event_filter.get_all_entries()
            print(f"Found {len(deposit_events)} potential Deposit events in the block range.")

            for event in deposit_events:
                print(f"\nProcessing Deposit event found in tx {event.transactionHash.hex()} (block {event.blockNumber})")
                print(f"  Raw event args: {event.args}") # DEBUG: Show raw args

                try:
                    args = event.args
                    token_address = args.token
                    user = args.user # Potential point of AttributeError if ABI mismatch
                    amount = args.amount
                    nonce = args.nonce

                    print(f"  Parsed - Token: {token_address}, User: {user}, Amount: {amount}, Nonce: {nonce}")

                    print("  Building 'wrap' transaction for destination chain...")
                    try:
                        warden_nonce_dest = w3_destination.eth.get_transaction_count(WARDEN_ADDRESS)
                        wrap_tx = destination_contract.functions.wrap(
                            token_address, user, amount, nonce
                        ).build_transaction({
                            'from': WARDEN_ADDRESS, 'gas': 2000000,
                            'gasPrice': w3_destination.eth.gas_price,
                            'nonce': warden_nonce_dest,
                            'chainId': w3_destination.eth.chain_id
                        })
                        signed_tx = w3_destination.eth.account.sign_transaction(wrap_tx, PRIVATE_KEY)
                        tx_hash = w3_destination.eth.send_raw_transaction(signed_tx.rawTransaction)
                        print(f"  Sent 'wrap' transaction to destination chain: {tx_hash.hex()}")
                        events_processed += 1
                    except ContractLogicError as cle:
                        print(f"  ERROR: Contract logic error sending 'wrap' tx: {cle}")
                    except Exception as e:
                        print(f"  ERROR: Failed to send 'wrap' transaction: {e}")

                except AttributeError as ae:
                    print(f"  ERROR: Skipping event due to missing attribute in event.args: {ae}. Check ABI definition for Deposit event.")
                    continue
                except Exception as e:
                    print(f"  ERROR: Unexpected error processing event args: {e}")
                    continue

        # Use the 'chain' parameter for logic
        elif chain == 'destination':
            unwrap_events = destination_contract.events.Unwrap.get_logs(
                from_block=start_block,
                to_block=latest_block
            )
            print(f"Found {len(unwrap_events)} potential Unwrap events in the block range.")

            for event in unwrap_events:
                print(f"\nProcessing Unwrap event found in tx {event.transactionHash.hex()} (block {event.blockNumber})")
                print(f"  Raw event args: {event.args}") # DEBUG: Show raw args

                try:
                    args = event.args
                    token_address = args.token
                    user = args.user # Potential point of AttributeError if ABI mismatch
                    amount = args.amount
                    nonce = args.nonce

                    print(f"  Parsed - Token: {token_address}, User: {user}, Amount: {amount}, Nonce: {nonce}")

                    print("  Building 'withdraw' transaction for source chain...")
                    try:
                        warden_nonce_source = w3_source.eth.get_transaction_count(WARDEN_ADDRESS)
                        withdraw_tx = source_contract.functions.withdraw(
                            token_address, user, amount, nonce
                        ).build_transaction({
                            'from': WARDEN_ADDRESS, 'gas': 2000000,
                            'gasPrice': w3_source.eth.gas_price,
                            'nonce': warden_nonce_source,
                            'chainId': w3_source.eth.chain_id
                        })
                        signed_tx = w3_source.eth.account.sign_transaction(withdraw_tx, PRIVATE_KEY)
                        tx_hash = w3_source.eth.send_raw_transaction(signed_tx.rawTransaction)
                        print(f"  Sent 'withdraw' transaction to source chain: {tx_hash.hex()}")
                        events_processed += 1
                    except ContractLogicError as cle:
                        print(f"  ERROR: Contract logic error sending 'withdraw' tx: {cle}")
                    except Exception as e:
                        print(f"  ERROR: Failed to send 'withdraw' transaction: {e}")

                except AttributeError as ae:
                    print(f"  ERROR: Skipping event due to missing attribute in event.args: {ae}. Check ABI definition for Unwrap event.")
                    continue
                except Exception as e:
                    print(f"  ERROR: Unexpected error processing event args: {e}")
                    continue

    except Exception as e:
        print(f"An unexpected error occurred during event scanning/processing: {e}")
        raise

    # Use the 'chain' parameter in the print statement
    print(f"\n--- Scan finished on '{chain}' chain. Processed {events_processed} events. ---")
    return events_processed

# --- Example Usage ---
if __name__ == "__main__":
    # Make sure contract_info.json exists and is correctly formatted
    # WARNING: Ensure the PRIVATE_KEY corresponds to the WARDEN_ADDRESS
    # and has funds on both testnets to pay for gas.

    try:
        print("Scanning source chain (Avalanche Testnet) for Deposit events...")
        # Call scan_blocks using the original parameter name 'chain'
        # The second argument uses the default value CONTRACT_INFO_PATH
        processed_source = scan_blocks('source')
        print(f"Completed source scan. Processed {processed_source} events.")

        print("\nScanning destination chain (BSC Testnet) for Unwrap events...")
         # Call scan_blocks using the original parameter name 'chain'
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