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
from json.decoder import JSONDecodeError

import requests

from nucypher.cli.actions import CHARACTER_DESTRUCTION
from nucypher.cli.actions.utils import UnknownIPAddress
from nucypher.cli.types import IPV4_ADDRESS


def destroy_configuration(emitter, character_config, force: bool = False) -> None:
    if not force:
        try:
            database = character_config.db_filepath
        except AttributeError:
            database = "No database found"

        click.confirm(CHARACTER_DESTRUCTION.format(name=character_config._NAME,
                                                   root=character_config.config_root,
                                                   keystore=character_config.keyring_root,
                                                   nodestore=character_config.node_storage.root_dir,
                                                   config=character_config.filepath,
                                                   database=database), abort=True)
    character_config.destroy()
    SUCCESSFUL_DESTRUCTION = "Successfully destroyed NuCypher configuration"
    emitter.message(SUCCESSFUL_DESTRUCTION, color='green')
    character_config.log.debug(SUCCESSFUL_DESTRUCTION)


def forget(emitter, configuration):
    """Forget all known nodes via storage"""
    click.confirm("Permanently delete all known node data?", abort=True)
    configuration.forget_nodes()
    message = "Removed all stored known nodes metadata and certificates"
    emitter.message(message, color='red')


def handle_missing_configuration_file(character_config_class, init_command_hint: str = None, config_file: str = None):
    config_file_location = config_file or character_config_class.default_filepath()
    init_command = init_command_hint or f"{character_config_class._NAME} init"
    message = f'No {character_config_class._NAME.capitalize()} configuration file found.\n' \
              f'To create a new persistent {character_config_class._NAME.capitalize()} run: ' \
              f'\'nucypher {init_command}\''

    raise click.FileError(filename=config_file_location, hint=message)


def get_or_update_configuration(emitter, config_class, filepath: str, config_options):

    try:
        config = config_class.from_configuration_file(filepath=filepath)
    except config_class.ConfigurationError:
        # Issue warning for invalid configuration...
        emitter.message(f"Invalid Configuration at {filepath}.")
        try:
            # ... but try to display it anyways
            response = config_class._read_configuration_file(filepath=filepath)
            return emitter.echo(json.dumps(response, indent=4))
        except JSONDecodeError:
            # ... sorry
            return emitter.message(f"Invalid JSON in Configuration File at {filepath}.")
    else:
        updates = config_options.get_updates()
        if updates:
            emitter.message(f"Updated configuration values: {', '.join(updates)}", color='yellow')
            config.update(**updates)
        return emitter.echo(config.serialize())


def get_external_ip_from_centralized_source() -> str:
    ip_request = requests.get('https://ifconfig.me/')
    if ip_request.status_code == 200:
        return ip_request.text
    raise UnknownIPAddress(f"There was an error determining the IP address automatically. "
                           f"(status code {ip_request.status_code})")


def determine_external_ip_address(emitter, force: bool = False) -> str:
    """
    Attempts to automatically get the external IP from ifconfig.me
    If the request fails, it falls back to the standard process.
    """
    try:
        rest_host = get_external_ip_from_centralized_source()
    except UnknownIPAddress:
        if force:
            raise
    else:
        # Interactive
        if not force:
            if not click.confirm(f"Is this the public-facing IPv4 address ({rest_host}) you want to use for Ursula?"):
                rest_host = click.prompt("Please enter Ursula's public-facing IPv4 address here:", type=IPV4_ADDRESS)
        else:
            emitter.message(f"WARNING: --force is set, using auto-detected IP '{rest_host}'", color='yellow')

        return rest_host