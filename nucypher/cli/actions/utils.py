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

import json
import os
import re
import shutil
from json.decoder import JSONDecodeError
from typing import Set, Optional, Dict, List

import click
from constant_sorrow.constants import (
    NO_CONTROL_PROTOCOL
)
from eth_utils.address import is_checksum_address
from nacl.exceptions import CryptoError
from twisted.python.log import Logger

from nucypher.blockchain.eth.clients import NuCypherGethGoerliProcess
from nucypher.blockchain.eth.interfaces import BlockchainInterface, BlockchainInterfaceFactory
from nucypher.blockchain.eth.registry import BaseContractRegistry, InMemoryContractRegistry, LocalContractRegistry
from nucypher.blockchain.eth.token import NU
from nucypher.cli.actions.auth import unlock_nucypher_keyring, get_nucypher_password
from nucypher.config.characters import UrsulaConfiguration
from nucypher.config.constants import DEFAULT_CONFIG_ROOT
from nucypher.network.exceptions import NodeSeemsToBeDown
from nucypher.network.middleware import RestMiddleware
from nucypher.network.nodes import Teacher
from nucypher.network.teachers import TEACHER_NODES

LOG = Logger('cli.actions')


class UnknownIPAddress(RuntimeError):
    pass


def establish_deployer_registry(emitter,
                                registry_infile: str = None,
                                registry_outfile: str = None,
                                use_existing_registry: bool = False,
                                download_registry: bool = False,
                                dev: bool = False
                                ) -> BaseContractRegistry:

    if download_registry:
        registry = InMemoryContractRegistry.from_latest_publication()
        emitter.message(f"Using latest published registry from {registry.source}")
        return registry

    # Establish a contract registry from disk if specified
    filepath = registry_infile
    default_registry_filepath = os.path.join(DEFAULT_CONFIG_ROOT, BaseContractRegistry.REGISTRY_NAME)
    if registry_outfile:
        registry_infile = registry_infile or default_registry_filepath
        if use_existing_registry:
            try:
                _result = shutil.copyfile(registry_infile, registry_outfile)
            except shutil.SameFileError:
                raise click.BadArgumentUsage(f"--registry-infile and --registry-outfile must not be the same path '{registry_infile}'.")
        filepath = registry_outfile

    if dev:
        # TODO: Need a way to detect a geth --dev registry filepath here. (then deprecate the --dev flag)
        filepath = os.path.join(DEFAULT_CONFIG_ROOT, BaseContractRegistry.DEVELOPMENT_REGISTRY_NAME)

    registry_filepath = filepath or default_registry_filepath

    # All Done.
    registry = LocalContractRegistry(filepath=registry_filepath)
    emitter.message(f"Configured to registry filepath {registry_filepath}")

    return registry


def get_registry(network: str, registry_filepath: str = None) -> BaseContractRegistry:
    if registry_filepath:
        registry = LocalContractRegistry(filepath=registry_filepath)
    else:
        registry = InMemoryContractRegistry.from_latest_publication(network=network)
    return registry


def connect_to_blockchain(provider_uri, emitter, debug: bool = False, light: bool = False) -> BlockchainInterface:
    try:
        # Note: Conditional for test compatibility.
        if not BlockchainInterfaceFactory.is_interface_initialized(provider_uri=provider_uri):
            BlockchainInterfaceFactory.initialize_interface(provider_uri=provider_uri,
                                                            light=light,
                                                            sync=False,
                                                            emitter=emitter)
        blockchain = BlockchainInterfaceFactory.get_interface(provider_uri=provider_uri)
        emitter.echo(message="Reading Latest Chaindata...")
        blockchain.connect()
        return blockchain
    except Exception as e:
        if debug:
            raise
        emitter.echo(str(e), bold=True, color='red')
        raise click.Abort


def load_static_nodes(domains: Set[str], filepath: Optional[str] = None) -> Dict[str, 'Ursula']:
    """
    Non-invasively read teacher-uris from a JSON configuration file keyed by domain name.
    and return a filtered subset of domains and teacher URIs as a dict.
    """

    if not filepath:
        filepath = os.path.join(DEFAULT_CONFIG_ROOT, 'static-nodes.json')
    try:
        with open(filepath, 'r') as file:
            static_nodes = json.load(file)
    except FileNotFoundError:
        return dict()   # No static nodes file, No static nodes.
    except JSONDecodeError:
        raise RuntimeError(f"Static nodes file '{filepath}' contains invalid JSON.")
    filtered_static_nodes = {domain: uris for domain, uris in static_nodes.items() if domain in domains}
    return filtered_static_nodes


def aggregate_seednode_uris(domains: set, highest_priority: Optional[List[str]] = None) -> List[str]:

    # Read from the disk
    static_nodes = load_static_nodes(domains=domains)

    # Priority 1 - URI passed via --teacher
    uris = highest_priority or list()
    for domain in domains:

        # 2 - Static nodes from JSON file
        domain_static_nodes = static_nodes.get(domain)
        if domain_static_nodes:
            uris.extend(domain_static_nodes)

        # 3 - Hardcoded teachers from module
        hardcoded_uris = TEACHER_NODES.get(domain)
        if hardcoded_uris:
            uris.extend(hardcoded_uris)

    return uris


def load_seednodes(emitter,
                   min_stake: int,
                   federated_only: bool,
                   network_domains: set,
                   network_middleware: RestMiddleware = None,
                   teacher_uris: list = None,
                   registry: BaseContractRegistry = None,
                   ) -> List:

    """
    Aggregates seednodes URI sources into a list or teacher URIs ordered
    by connection priority in the following order:

    1. --teacher CLI flag
    2. static-nodes.json
    3. Hardcoded teachers
    """

    # Heads up
    emitter.message("Connecting to preferred teacher nodes...", color='yellow')
    from nucypher.characters.lawful import Ursula

    # Aggregate URIs (Ordered by Priority)
    teacher_nodes = list()  # type: List[Ursula]
    teacher_uris = aggregate_seednode_uris(domains=network_domains, highest_priority=teacher_uris)
    if not teacher_uris:
        emitter.message(f"No teacher nodes available for domains: {','.join(network_domains)}")
        return teacher_nodes

    # Construct Ursulas
    for uri in teacher_uris:
        try:
            teacher_node = Ursula.from_teacher_uri(teacher_uri=uri,
                                                   min_stake=min_stake,
                                                   federated_only=federated_only,
                                                   network_middleware=network_middleware,
                                                   registry=registry)
        except NodeSeemsToBeDown:
            LOG.info(f"Failed to connect to teacher: {uri}")
            continue
        except Teacher.NotStaking:
            LOG.info(f"Teacher: {uri} is not actively staking, skipping")
            continue
        teacher_nodes.append(teacher_node)

    if not teacher_nodes:
        emitter.message(f"WARNING - No Peers Available for domains: {','.join(network_domains)}")
    return teacher_nodes


def get_provider_process(start_now: bool = False):

    """
    Stage integrated ethereum node process
    # TODO: Support domains and non-geth clients
    """
    process = NuCypherGethGoerliProcess()
    if start_now:
        process.start()
    return process


def make_cli_character(character_config,
                       emitter,
                       unlock_keyring: bool = True,
                       teacher_uri: str = None,
                       min_stake: int = 0,
                       load_preferred_teachers: bool = True,
                       **config_args):

    #
    # Pre-Init
    #

    # Handle Keyring

    if unlock_keyring:
        unlock_nucypher_keyring(emitter,
                                character_configuration=character_config,
                                password=get_nucypher_password(confirm=False))

    # Handle Teachers
    teacher_nodes = list()
    if load_preferred_teachers:
        teacher_nodes = load_seednodes(emitter,
                                       teacher_uris=[teacher_uri] if teacher_uri else None,
                                       min_stake=min_stake,
                                       federated_only=character_config.federated_only,
                                       network_domains=character_config.domains,
                                       network_middleware=character_config.network_middleware,
                                       registry=character_config.registry)

    #
    # Character Init
    #

    # Produce Character
    try:
        CHARACTER = character_config(known_nodes=teacher_nodes,
                                     network_middleware=character_config.network_middleware,
                                     **config_args)
    except (CryptoError, ValueError):
        raise character_config.keyring.AuthenticationFailed(f"Failed to unlock nucypher keyring. "
                                                            "Are you sure you provided the correct password?")

    #
    # Post-Init
    #

    if CHARACTER.controller is not NO_CONTROL_PROTOCOL:
        CHARACTER.controller.emitter = emitter  # TODO: set it on object creation? Or not set at all?

    # Federated
    if character_config.federated_only:
        emitter.message("WARNING: Running in Federated mode", color='yellow')

    return CHARACTER


def extract_checksum_address_from_filepath(filepath, config_class=UrsulaConfiguration):

    pattern = re.compile(r'''
                         (^\w+)-
                         (0x{1}         # Then, 0x the start of the string, exactly once
                         [0-9a-fA-F]{40}) # Followed by exactly 40 hex chars
                         ''',
                         re.VERBOSE)

    filename = os.path.basename(filepath)
    match = pattern.match(filename)

    if match:
        character_name, checksum_address = match.groups()

    else:
        # Extract from default by "peeking" inside the configuration file.
        default_name = config_class.generate_filename()
        if filename == default_name:
            checksum_address = config_class.peek(filepath=filepath, field='checksum_address')

            ###########
            # TODO: Cleanup and deprecate worker_address in config files, leaving only checksum_address
            if config_class == UrsulaConfiguration:
                federated = bool(config_class.peek(filepath=filepath, field='federated_only'))
                if not federated:
                    checksum_address = config_class.peek(filepath=filepath, field='worker_address')
            ###########

        else:
            raise ValueError(f"Cannot extract checksum from filepath '{filepath}'")

    if not is_checksum_address(checksum_address):
        raise RuntimeError(f"Invalid checksum address detected in configuration file at '{filepath}'.")
    return checksum_address


def issue_stake_suggestions(value: NU = None, lock_periods: int = None) -> None:
    if value and (value > NU.from_tokens(150000)):
        click.confirm(f"Wow, {value} - That's a lot of NU - Are you sure this is correct?", abort=True)
    if lock_periods and (lock_periods > 365):
        click.confirm(f"Woah, {lock_periods} is a long time - Are you sure this is correct?", abort=True)