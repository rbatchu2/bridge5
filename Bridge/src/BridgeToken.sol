// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";

contract BridgeToken is ERC20, ERC20Burnable, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
	address public underlying;

    constructor( address _underlying, string memory name, string memory symbol, address admin ) ERC20(name,symbol) {
		underlying = _underlying;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(MINTER_ROLE, admin);
    }

    function mint(address to, uint256 amount) public onlyRole(MINTER_ROLE) {
        _mint(to, amount);
    }

    function clawBack(address account, uint256 amount) public onlyRole(MINTER_ROLE) {
        _burn(account, amount);
    }

    function burnFrom(address account, uint256 amount) public override {
		/*
		   Override OpenZeppelin's burnFrom function to allow the MINTER_ROLE to burn without an allowance
		*/
		if( ! hasRole(MINTER_ROLE,msg.sender) ) {
			_spendAllowance(account, _msgSender(), amount);
		}
        _burn(account, amount);
    }
}


