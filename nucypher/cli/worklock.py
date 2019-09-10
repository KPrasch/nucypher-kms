"""
This file is part of nucypher.

nucypher is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

nucypher is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with nucypher.  If not, see <https://www.gnu.org/licenses/>.

"""
from datetime import datetime

import click
from web3 import Web3

from nucypher.blockchain.eth.agents import ContractAgency, WorkLockAgent, NucypherTokenAgent
from nucypher.blockchain.eth.interfaces import BlockchainInterfaceFactory
from nucypher.blockchain.eth.registry import InMemoryContractRegistry
from nucypher.characters.banners import WORKLOCK_BANNER
from nucypher.cli.actions import select_client_account
from nucypher.cli.config import nucypher_click_config
from nucypher.cli.painting import paint_receipt_summary
from nucypher.cli.types import EIP55_CHECKSUM_ADDRESS, WEI


@click.command()
@click.argument('action')
@click.option('--force', help="Don't ask for confirmation", is_flag=True)
@click.option('--sync/--no-sync', default=False)
@click.option('--poa', help="Inject POA middleware", is_flag=True, default=False)
@click.option('--provider', 'provider_uri', help="Blockchain provider's URI", type=click.STRING, default="auto://")
@click.option('--bidder-address', help="Bidding address.", type=EIP55_CHECKSUM_ADDRESS)
@click.option('--bid', help="Bid amount in wei", type=WEI)
@nucypher_click_config
def worklock(click_config, action, force, provider_uri, sync, poa, bidder_address, bid):
    """Participate in NU token worklock bidding."""

    emitter = click_config.emitter
    click.clear()
    emitter.banner(WORKLOCK_BANNER)

    try:

        BlockchainInterfaceFactory.initialize_interface(provider_uri=provider_uri, sync=sync, poa=poa)
        blockchain = BlockchainInterfaceFactory.get_interface(provider_uri=provider_uri)
        registry = InMemoryContractRegistry.from_latest_publication()
        WORKLOCK_AGENT = ContractAgency.get_agent(WorkLockAgent, registry=registry)

        #
        # Read-Only Actions
        #

        if action == "status":
            from maya import MayaDT

            # Agency
            token_agent = ContractAgency.get_agent(NucypherTokenAgent, registry=registry)

            # Time
            start = MayaDT( WORKLOCK_AGENT.contract.functions.startBidDate().call())
            end = MayaDT(WORKLOCK_AGENT.contract.functions.endBidDate().call())
            duration = end - start
            remaining = end - datetime.now()

            payload = f"""
            
            Time
            ======================================================
            Start Date ........ {start}
            End Date .......... {end}
            Duration .......... {duration}
            Time Remaining .... {remaining} 
            
            Economics
            ======================================================            
            Max. Locked ....... {WORKLOCK_AGENT.contract.functions.minAllowableLockedTokens().call()}
            Min. Locked ....... {WORKLOCK_AGENT.contract.functions.maxAllowableLockedTokens().call()}
            Deposit Rate ...... {WORKLOCK_AGENT.contract.functions.depositRate().call()} 
            Refund Rate ....... {WORKLOCK_AGENT.contract.functions.refundRate().call()}
            Total Bids ........ {blockchain.client.get_balance(WORKLOCK_AGENT.contract_address)}
            Claimed Tokens .... {WORKLOCK_AGENT.contract.functions.allClaimedTokens().call()}
            Remaining Tokens .. {token_agent.get_balance(WORKLOCK_AGENT.contract_address)}

            """
            emitter.message(payload)
            return  # Exit

        #
        # Action Switch with Bid address
        #

        if not bidder_address:
            bidder_address = select_client_account(emitter=emitter, provider_uri=provider_uri)
            if force:
                raise click.MissingParameter("Missing --bidder-address.")

        if action == "remaining-work":
            remaining_work = WORKLOCK_AGENT.get_remaining_work(sender_address=bidder_address)
            emitter.message(f"Work Remaining: {remaining_work}")
            return  # Exit

        #
        # Authenticated Action Switch
        #

        if not bid:
            bid = Web3.fromWei(click.prompt("Enter bid amount in ETH", type=click.FloatRange(min=0)), 'wei')
            if force:
                raise click.MissingParameter("Missing --bid.")

        if action == "bid":
            receipt = WORKLOCK_AGENT.bid(sender_address=bidder_address, eth_amount=bid)
            emitter.message("Publishing Bid...")
            if not force:
                click.confirm(f"Place bid of {Web3.fromWei(bid, 'ether')} ETH?", abort=True)
            paint_receipt_summary(receipt=receipt, emitter=emitter, chain_name=blockchain.client.chain_name)
            return  # Exit

        elif action == "claim":
            receipt = WORKLOCK_AGENT.claim(sender_address=bidder_address)
            emitter.message("Claiming...")
            if not force:
                click.confirm(f"Claim tokens for  bidder {bidder_address}?", abort=True)
            paint_receipt_summary(receipt=receipt, emitter=emitter, chain_name=blockchain.client.chain_name)
            return  # Exit

        elif action == "refund":
            receipt = WORKLOCK_AGENT.refund(sender_address=bidder_address)
            emitter.message("Submitting Refund...")
            if not force:
                click.confirm(f"Collect ETH refund for bidder {bidder_address}?", abort=True)
            paint_receipt_summary(receipt=receipt, emitter=emitter, chain_name=blockchain.client.chain_name)
            return  # Exit

        else:
            raise click.BadArgumentUsage(f"No such action '{action}'")

    except Exception as e:
        if click_config.debug:
            raise
        click.secho(str(e), bold=True, fg='red')
        return  # Exit
