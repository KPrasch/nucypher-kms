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

import glob
import os
from typing import Tuple

from tabulate import tabulate

from nucypher.blockchain.eth.actors import Staker
from nucypher.blockchain.eth.interfaces import BlockchainInterfaceFactory
from nucypher.blockchain.eth.networks import NetworksInventory
from nucypher.blockchain.eth.registry import InMemoryContractRegistry, IndividualAllocationRegistry
from nucypher.blockchain.eth.signers import Signer
from nucypher.blockchain.eth.token import NU, Stake
from nucypher.cli.actions.utils import extract_checksum_address_from_filepath
from nucypher.config.constants import DEFAULT_CONFIG_ROOT, NUCYPHER_ENVVAR_WORKER_ADDRESS


def select_client_account(emitter,
                          provider_uri: str = None,
                          signer_uri: str = None,
                          wallet: Wallet = None,
                          prompt: str = None,
                          default: int = 0,
                          registry=None,
                          show_eth_balance: bool = False,
                          show_nu_balance: bool = False,
                          show_staking: bool = False,
                          network: str = None,
                          poa: bool = None
                          ) -> str:
    """
    Note: Showing ETH and/or NU balances, causes an eager blockchain connection.
    """

    # We use Wallet internally as an account management abstraction
    if not wallet:
        if not provider_uri and not signer_uri:
            raise ValueError("At least a provider URI or signer URI is necessary to select an account")
        # Lazy connect the blockchain interface
        if not BlockchainInterfaceFactory.is_interface_initialized(provider_uri=provider_uri):
            BlockchainInterfaceFactory.initialize_interface(provider_uri=provider_uri, poa=poa, emitter=emitter)
        signer = Signer.from_signer_uri(signer_uri) if signer_uri else None
        wallet = Wallet(provider_uri=provider_uri, signer=signer)
    elif provider_uri or signer_uri:
        raise ValueError("If you input a wallet, don't pass a provider URI or signer URI too")

    # Display accounts info
    if show_nu_balance or show_staking:  # Lazy registry fetching
        if not registry:
            registry = InMemoryContractRegistry.from_latest_publication(network=network)

    wallet_accounts = wallet.accounts
    enumerated_accounts = dict(enumerate(wallet_accounts))
    if len(enumerated_accounts) < 1:
        emitter.echo("No ETH accounts were found.", color='red', bold=True)
        raise click.Abort()

    # Display account info
    headers = ['Account']
    if show_staking:
        headers.append('Staking')
    if show_eth_balance:
        headers.append('ETH')
    if show_nu_balance:
        headers.append('NU')

    rows = list()
    for index, account in enumerated_accounts.items():
        row = [account]
        if show_staking:
            staker = Staker(is_me=True, checksum_address=account, registry=registry)
            staker.stakes.refresh()
            is_staking = 'Yes' if bool(staker.stakes) else 'No'
            row.append(is_staking)
        if show_eth_balance:
            ether_balance = Web3.fromWei(wallet.eth_balance(account), 'ether')
            row.append(f'{ether_balance} ETH')
        if show_nu_balance:
            token_balance = NU.from_nunits(wallet.token_balance(account, registry))
            row.append(token_balance)
        rows.append(row)
    emitter.echo(tabulate(rows, headers=headers, showindex='always'))

    # Prompt the user for selection, and return
    prompt = prompt or "Select index of account"
    account_range = click.IntRange(min=0, max=len(enumerated_accounts)-1)
    choice = click.prompt(prompt, type=account_range, default=default)
    chosen_account = enumerated_accounts[choice]

    emitter.echo(f"Selected {choice}: {chosen_account}", color='blue')
    return chosen_account


def select_stake(stakeholder, emitter, divisible: bool = False, staker_address: str = None) -> Stake:
    if staker_address:
        staker = stakeholder.get_staker(checksum_address=staker_address)
        stakes = staker.stakes
    else:
        stakes = stakeholder.all_stakes
    if not stakes:
        emitter.echo(f"No stakes found.", color='red')
        raise click.Abort

    stakes = sorted((stake for stake in stakes if stake.is_active), key=lambda s: s.address_index_ordering_key)
    if divisible:
        emitter.echo("NOTE: Showing divisible stakes only", color='yellow')
        stakes = list(filter(lambda s: bool(s.value >= stakeholder.economics.minimum_allowed_locked*2), stakes))  # TODO: Move to method on Stake
        if not stakes:
            emitter.echo(f"No divisible stakes found.", color='red')
            raise click.Abort
    enumerated_stakes = dict(enumerate(stakes))
    painting.paint_stakes(stakeholder=stakeholder, emitter=emitter, staker_address=staker_address)
    choice = click.prompt("Select Stake", type=click.IntRange(min=0, max=len(enumerated_stakes)-1))
    chosen_stake = enumerated_stakes[choice]
    return chosen_stake


def select_config_file(emitter,
                       config_class,
                       config_root: str = None,
                       checksum_address: str = None,
                       ) -> str:

    #
    # Scrape Disk Configurations
    #

    config_root = config_root or DEFAULT_CONFIG_ROOT
    default_config_file = glob.glob(config_class.default_filepath(config_root=config_root))
    glob_pattern = f'{config_root}/{config_class._NAME}-0x*.{config_class._CONFIG_FILE_EXTENSION}'
    secondary_config_files = glob.glob(glob_pattern)
    config_files = [*default_config_file, *secondary_config_files]
    if not config_files:
        emitter.message(f"No {config_class._NAME.capitalize()} configurations found.  "
                        f"run 'nucypher {config_class._NAME} init' then try again.", color='red')
        raise click.Abort()

    checksum_address = checksum_address or os.environ.get(NUCYPHER_ENVVAR_WORKER_ADDRESS, None)  # TODO: Deprecate worker_address in favor of checksum_address
    if checksum_address:

        #
        # Manual
        #

        parsed_addresses = {extract_checksum_address_from_filepath(fp): fp for fp in config_files}
        try:
            config_file = parsed_addresses[checksum_address]
        except KeyError:
            raise ValueError(f"'{checksum_address}' is not a known {config_class._NAME} configuration account.")

    elif len(config_files) > 1:

        #
        # Interactive
        #

        parsed_addresses = tuple([extract_checksum_address_from_filepath(fp)] for fp in config_files)

        # Display account info
        headers = ['Account']
        emitter.echo(tabulate(parsed_addresses, headers=headers, showindex='always'))

        # Prompt the user for selection, and return
        prompt = f"Select {config_class._NAME} configuration"
        account_range = click.IntRange(min=0, max=len(config_files) - 1)
        choice = click.prompt(prompt, type=account_range, default=0)
        config_file = config_files[choice]
        emitter.echo(f"Selected {choice}: {config_file}", color='blue')

    else:
        # Default: Only one config file, use it.
        config_file = config_files[0]

    return config_file


def select_network(emitter) -> str:
    headers = ["Network"]
    rows = [[n] for n in NetworksInventory.NETWORKS]
    emitter.echo(tabulate(rows, headers=headers, showindex='always'))
    choice = click.prompt("Select Network", default=0, type=click.IntRange(0, len(NetworksInventory.NETWORKS)-1))
    network = NetworksInventory.NETWORKS[choice]
    return network


def select_client_account_for_staking(emitter,
                                      stakeholder,
                                      staking_address: str,
                                      individual_allocation: IndividualAllocationRegistry,
                                      force: bool,
                                      ) -> Tuple[str, str]:
    """
    Manages client account selection for stake-related operations.
    It always returns a tuple of addresses: the first is the local client account and the second is the staking address.

    When this is not a preallocation staker (which is the normal use case), both addresses are the same.
    Otherwise, when the staker is a contract managed by a beneficiary account,
    then the local client account is the beneficiary, and the staking address is the address of the staking contract.
    """

    if individual_allocation:
        client_account = individual_allocation.beneficiary_address
        staking_address = individual_allocation.contract_address

        message = f"Beneficiary {client_account} will use preallocation contract {staking_address} to stake."
        emitter.echo(message, color='yellow', verbosity=1)
        if not force:
            click.confirm("Is this correct?", abort=True)
    else:
        if staking_address:
            client_account = staking_address
        else:
            client_account = select_client_account(prompt="Select index of staking account",
                                                   emitter=emitter,
                                                   registry=stakeholder.registry,
                                                   network=stakeholder.network,
                                                   wallet=stakeholder.wallet)
            staking_address = client_account

    return client_account, staking_address