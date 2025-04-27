// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.17;

import "forge-std/Test.sol";
import "../src/Destination.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MToken is ERC20 {
	constructor(string memory name, string memory symbol,uint256 supply) ERC20(name,symbol) {
		_mint(msg.sender, supply );
	}
}

contract DestinationTest is Test {
    Destination public destination;

	uint256 admin_sk = uint256(keccak256(abi.encodePacked("admin")));
	address admin = vm.addr(admin_sk);
	uint256 token_owner_sk = uint256(keccak256(abi.encodePacked("token owner")));
	address token_owner = vm.addr(token_owner_sk);
	ERC20 underlying_token;
	uint256 max_amount = 1<<250;

	event Creation( address indexed underlying_token, address indexed wrapped_token );
	event Wrap( address indexed underlying_token, address indexed wrapped_token, address indexed to, uint256 amount );
	event Unwrap( address indexed underlying_token, address indexed wrapped_token, address frm, address indexed to, uint256 amount );

    function setUp() public {
		destination = new Destination(admin);
		string memory _name = "Pteranodon";
		string memory _symbol = "PTE";
		underlying_token = new MToken(_name,_symbol,max_amount);
    }

	function testCreation() public returns(address) {
		vm.expectEmit(true,false,false,false);
		emit Creation(address(underlying_token),address(0));

		vm.startPrank(admin);
		address wtoken = destination.createToken(address(underlying_token),string.concat("w",underlying_token.name()),string.concat("w",underlying_token.symbol()) );
		vm.stopPrank();

		assertEq( destination.wrapped_tokens(address(underlying_token)), wtoken );
		assertEq( destination.underlying_tokens(wtoken), address(underlying_token) );

		return wtoken;
	}

	function testUnauthorizedCreation(address user) public{
		vm.assume( user != address(0) );
		vm.assume( user != admin );

		string memory _name = underlying_token.name();
		string memory _symbol = underlying_token.symbol();
		vm.expectRevert();
		vm.prank(user);
		destination.createToken(address(underlying_token),string.concat("w",_name),string.concat("w",_symbol) );
	}

    function testApprovedWrap(address depositor, address s_recipient, address d_recipient, uint256 amount) public {
		vm.assume( s_recipient != address(0) );
		vm.assume( d_recipient != address(0) );
		vm.assume( depositor != address(0) );
		vm.assume( depositor != admin );
		vm.assume( s_recipient != admin );
		vm.assume( d_recipient != admin );
		vm.assume( s_recipient != d_recipient );
		vm.assume( depositor != s_recipient );
		vm.assume( depositor != d_recipient );
		vm.assume( amount < max_amount );
		vm.assume( amount > 0 );

		address wtoken = testCreation();

		assertEq( destination.wrapped_tokens(address(underlying_token)), wtoken );
		assertEq( destination.underlying_tokens(wtoken), address(underlying_token) );

		uint256 previous_balance = ERC20(wtoken).balanceOf(d_recipient);
		vm.expectEmit(true,true,true,true);
		emit Wrap(address(underlying_token),wtoken,d_recipient,amount);
		vm.prank(admin);
		destination.wrap(address(underlying_token),d_recipient, amount);
		assertEq( ERC20(wtoken).balanceOf(d_recipient), previous_balance + amount );

		vm.expectEmit(true,true,true,true);
		emit Unwrap(address(underlying_token),wtoken,d_recipient,s_recipient,amount);
		vm.prank(d_recipient);
		destination.unwrap(wtoken,s_recipient, amount);
    }

    function testUnapprovedApprovedWrap(address user, address d_recipient, uint256 amount) public {
		vm.assume( d_recipient != address(0) );
		vm.assume( user != address(0) );
		vm.assume( user != admin );
		vm.assume( d_recipient != admin );
		vm.assume( amount < max_amount );
		vm.assume( amount > 0 );

		vm.prank(user);
		vm.expectRevert();
		destination.wrap(address(underlying_token),d_recipient, amount);
    }

    function testUnregisteredApprovedWrap(address token_address, address d_recipient, uint256 amount) public {
		vm.assume( d_recipient != address(0) );
		vm.assume( d_recipient != admin );
		vm.assume( amount < max_amount );
		vm.assume( amount > 0 );
		vm.assume( token_address != address(underlying_token) );
		vm.assume( token_address != address(0) );

		vm.prank(admin);
		vm.expectRevert();
		destination.wrap(token_address,d_recipient, amount);
    }

	function testUnwrap(address user, address recipient, uint256 amount ) public {
		vm.assume( amount > 0 );
		vm.assume( user != address(0) );
		vm.assume( recipient != address(0) );
		address wtoken = testCreation();

		vm.prank(admin);
		destination.wrap(address(underlying_token),user, amount);

		uint256 prev_balance = ERC20(wtoken).balanceOf( user );

		vm.prank(user);
		vm.expectEmit(true,true,true,true);
		emit Unwrap( address(underlying_token), wtoken, user, user, amount );
		destination.unwrap(wtoken, user, amount);

		assertEq( ERC20(wtoken).balanceOf(user), prev_balance - amount );
	}		

}
