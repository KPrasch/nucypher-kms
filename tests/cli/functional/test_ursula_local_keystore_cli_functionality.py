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
from eth_account import Account
from pathlib import Path

from nucypher.blockchain.eth.signers import KeystoreSigner
from nucypher.blockchain.eth.token import StakeList
from nucypher.cli.main import nucypher_cli
from nucypher.config.characters import UrsulaConfiguration
from nucypher.config.constants import TEMPORARY_DOMAIN
from tests.constants import (
    CLI_ENV, INSECURE_DEVELOPMENT_PASSWORD,
    MOCK_IP_ADDRESS,
    TEST_PROVIDER_URI,
    MOCK_KEYSTORE_PATH,
    MOCK_SIGNER_URI
)
from tests.utils.ursula import MOCK_URSULA_STARTING_PORT


def test_ursula_init_with_local_keystore_signer(click_runner,
                                                patch_keystore,
                                                custom_filepath,
                                                custom_config_filepath,
                                                mocker,
                                                mock_testerchain,
                                                worker_account,
                                                test_registry_source_manager):

    # Good signer...
    pre_config_signer = KeystoreSigner.from_signer_uri(uri=MOCK_SIGNER_URI)

    init_args = ('ursula', 'init',
                 '--network', TEMPORARY_DOMAIN,
                 '--worker-address', worker_account.address,
                 '--config-root', custom_filepath,
                 '--provider', TEST_PROVIDER_URI,
                 '--rest-host', MOCK_IP_ADDRESS,
                 '--rest-port', MOCK_URSULA_STARTING_PORT,

                 # The bit we are testing here
                 '--signer', MOCK_SIGNER_URI)

    result = click_runner.invoke(nucypher_cli, init_args, catch_exceptions=False, env=CLI_ENV)
    assert result.exit_code == 0, result.stdout

    # Inspect the configuration file for the signer URI
    with open(custom_config_filepath, 'r') as config_file:
        raw_config_data = config_file.read()
        config_data = json.loads(raw_config_data)
        assert config_data['signer_uri'] == MOCK_SIGNER_URI,\
            "Keystore URI was not correctly included in configuration file"

    # Recreate a configuration with the signer URI preserved
    ursula_config = UrsulaConfiguration.from_configuration_file(custom_config_filepath)
    assert ursula_config.signer_uri == MOCK_SIGNER_URI

    # Mock decryption of web3 client keyring
    mocker.patch.object(Account, 'decrypt', return_value=worker_account.privateKey)
    ursula_config.attach_keyring(checksum_address=worker_account.address)
    ursula_config.keyring.unlock(password=INSECURE_DEVELOPMENT_PASSWORD)

    # Produce an ursula with a Keystore signer correctly derived from the signer URI, and dont do anything else!
    mocker.patch.object(StakeList, 'refresh', autospec=True)
    ursula = ursula_config.produce(client_password=INSECURE_DEVELOPMENT_PASSWORD,
                                   block_until_ready=False)

    # Verify the keystore path is still preserved
    assert isinstance(ursula.signer, KeystoreSigner)
    assert isinstance(ursula.signer.path, Path), "Use Pathlib"
    assert ursula.signer.path == Path(MOCK_KEYSTORE_PATH)  # confirm Pathlib is used internally despite string input

    # Show that we can produce the exact same signer as pre-config...
    assert pre_config_signer.path == ursula.signer.path
