// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.17;

import "forge-std/Test.sol";
import "../src/Source.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MToken is ERC20 {
	constructor(string memory name, string memory symbol,uint256 supply) ERC20(name,symbol) {
		_mint(msg.sender, supply );
	}
}

contract SourceTest is Test {
    Source public source;

	uint256 admin_sk = uint256(keccak256(abi.encodePacked("admin")));
	address admin = vm.addr(admin_sk);
	uint256 token_owner_sk = uint256(keccak256(abi.encodePacked("token owner")));
	address token_owner = vm.addr(token_owner_sk);

	event Deposit( address indexed token, address indexed recipient, uint256 amount );
	event Withdrawal( address indexed token, address indexed recipient, uint256 amount );
	event Registration( address indexed token );


    function setUp() public {
		source = new Source(admin);
    }

    function testApprovedRegistration( uint256 supply ) public returns( address ){
		vm.assume( supply > 0 );
		vm.assume( supply < 2**250 );

		vm.prank(token_owner);
		ERC20 token = new MToken('Triceratops','TRI',5*supply );

		vm.expectEmit(true,false,false,true);
		emit Registration(address(token));
		vm.prank(admin);
		source.registerToken(address(token));
	
		assertTrue( source.approved( address(token) ) );

		return address(token);
    }

	function testUnapprovedRegistration( address registrant ) public {
		vm.assume( registrant != admin );

		vm.prank(token_owner);
		ERC20 token = new MToken('Triceratops','TRI', 100 );

		vm.expectRevert();
		vm.prank(registrant);
		source.registerToken(address(token));
		
	}


    function testApprovedDeposit(address depositor, address recipient, uint256 amount) public returns( address ){
		vm.assume( recipient != address(0) );
		vm.assume( depositor != address(0) );
		vm.assume( depositor != admin );
		vm.assume( recipient != admin );
		vm.assume( depositor != recipient );
		vm.assume( depositor != token_owner );
		vm.assume( depositor != address(source) );
		vm.assume( amount < 1<<250 );
		vm.assume( amount > 0 );

		address token_address = testApprovedRegistration(amount);
		MToken token = MToken(token_address);

		vm.prank(token_owner);
		token.transfer( depositor, 2*amount );

		vm.prank(depositor);
		token.approve( address(source), amount );

		uint256 previous_balance = token.balanceOf(depositor);
		uint256 previous_source_balance = token.balanceOf(address(source));
		vm.expectEmit(true,true,false,true);
		emit Deposit( address(token), recipient, amount );
		vm.prank(depositor);
		source.deposit( address(token), recipient, amount );

		assertEq( amount, previous_balance - token.balanceOf(depositor) );
		assertEq( amount, token.balanceOf(address(source)) - previous_source_balance );

		return address(token);
    }

    function testUnapprovedDeposit(address depositor, address recipient, uint256 amount) public {
		vm.assume( recipient != address(0) );
		vm.assume( depositor != address(0) );
		vm.assume( depositor != admin );
		vm.assume( recipient != admin );
		vm.assume( depositor != recipient );
		vm.assume( amount < 1<<250 );
		vm.assume( amount > 0 );

		vm.prank(token_owner);
		ERC20 token = new MToken('Triceratops','TRI',5*amount );

		vm.prank(token_owner);
		token.transfer( depositor, 2*amount );

		vm.prank(depositor);
		token.approve( address(source), amount );

		vm.prank(depositor);
		vm.expectRevert();
		source.deposit( address(token), recipient, amount );

    }

    function testApprovedWithdrawal(address depositor, address recipient, uint256 amount) public {
		vm.assume( recipient != address(0) );
		vm.assume( depositor != address(0) );
		vm.assume( depositor != admin );
		vm.assume( recipient != admin );
		vm.assume( depositor != recipient );
		vm.assume( amount < 1<<250 );
		vm.assume( amount > 10 );

		uint256 withdraw_amount = amount - 10;
		address token_address = testApprovedDeposit( depositor, recipient, amount );
		MToken token = MToken(token_address);
		uint256 previous_balance = token.balanceOf(depositor);
		uint256 previous_source_balance = token.balanceOf(address(source));

		vm.prank(admin);
		vm.expectEmit(true,true,false,true);
		emit Withdrawal( token_address, depositor, withdraw_amount );
		source.withdraw( token_address, depositor, withdraw_amount );

		assertEq( withdraw_amount, token.balanceOf(depositor) - previous_balance );
		assertEq( withdraw_amount, previous_source_balance - token.balanceOf(address(source)) );

    }

    function testUnapprovedWithdrawal(address withdrawer, address depositor, address recipient, uint256 amount) public {
		vm.assume( recipient != address(0) );
		vm.assume( depositor != address(0) );
		vm.assume( depositor != admin );
		vm.assume( recipient != admin );
		vm.assume( withdrawer != admin );
		vm.assume( depositor != recipient );
		vm.assume( amount < 1<<250 );
		vm.assume( amount > 20 );

		uint256 withdraw_amount = amount - 10;
		address token_address = testApprovedDeposit( depositor, recipient, amount );

		vm.prank(withdrawer);
		vm.expectRevert();
		source.withdraw( token_address, depositor, withdraw_amount );

    }

}
