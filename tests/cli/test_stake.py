import json
import os

import pytest

from nucypher.blockchain.eth.actors import StakeHolder
from nucypher.blockchain.eth.agents import StakingEscrowAgent, Agency
from nucypher.blockchain.eth.token import NU
from nucypher.cli.main import nucypher_cli
from nucypher.utilities.sandbox.constants import (
    MOCK_CUSTOM_INSTALLATION_PATH,
    TEST_PROVIDER_URI,
    INSECURE_DEVELOPMENT_PASSWORD,
    MOCK_REGISTRY_FILEPATH)


@pytest.fixture(scope='module')
def configuration_file_location(custom_filepath):
    _configuration_file_location = os.path.join(MOCK_CUSTOM_INSTALLATION_PATH, StakeHolder.generate_filename())
    return _configuration_file_location


@pytest.fixture(scope='module')
def mock_registry_filepath(testerchain):

    registry = testerchain.registry

    # Fake the source contract registry
    with open(MOCK_REGISTRY_FILEPATH, 'w') as file:
        file.write(json.dumps(registry.read()))

    yield MOCK_REGISTRY_FILEPATH

    if os.path.isfile(MOCK_REGISTRY_FILEPATH):
        os.remove(MOCK_REGISTRY_FILEPATH)


def test_stake_new_stakeholder(click_runner,
                               custom_filepath,
                               configuration_file_location,
                               mock_registry_filepath,
                               staking_participant):

    init_args = ('stake', 'new-stakeholder',
                 '--poa',
                 '--funding-address', staking_participant.checksum_address,
                 '--config-root', custom_filepath,
                 '--provider-uri', TEST_PROVIDER_URI,
                 '--registry-filepath', mock_registry_filepath)

    user_input = '{password}\n{password}'.format(password=INSECURE_DEVELOPMENT_PASSWORD)
    result = click_runner.invoke(nucypher_cli,
                                 init_args,
                                 input=user_input,
                                 catch_exceptions=False)
    assert result.exit_code == 0
    assert os.path.exists(configuration_file_location)


def test_stake_init(click_runner,
                    configuration_file_location,
                    # funded_blockchain,
                    stake_value,
                    token_economics):

    stake_args = ('stake', 'init',
                  '--config-file', configuration_file_location,
                  '--value', stake_value.to_tokens(),
                  '--duration', token_economics.minimum_locked_periods,
                  '--force')

    result = click_runner.invoke(nucypher_cli, stake_args, input=INSECURE_DEVELOPMENT_PASSWORD, catch_exceptions=False)
    assert result.exit_code == 0

    with open(configuration_file_location, 'r') as config_file:
        config_data = json.loads(config_file.read())

    # Verify the stake is on-chain
    staking_agent = Agency.get_agent(StakingEscrowAgent)
    stakes = list(staking_agent.get_all_stakes(staker_address=config_data['checksum_address']))
    assert len(stakes) == 1
    start_period, end_period, value = stakes[0]
    assert NU(int(value), 'NuNit') == stake_value


def test_stake_list(click_runner,
                    funded_blockchain,
                    configuration_file_location,
                    stake_value):
    stake_args = ('stake', 'list',
                  '--config-file', configuration_file_location,
                  '--poa')

    user_input = f'{INSECURE_DEVELOPMENT_PASSWORD}'
    result = click_runner.invoke(nucypher_cli, stake_args, input=user_input, catch_exceptions=False)
    assert result.exit_code == 0
    assert str(stake_value) in result.output


def test_stake_divide(click_runner, configuration_file_location, token_economics):

    divide_args = ('stake', 'divide',
                   '--config-file', configuration_file_location,
                   '--force',
                   '--index', 0,
                   '--value', NU(token_economics.minimum_allowed_locked, 'NuNit').to_tokens(),
                   '--duration', 10)

    result = click_runner.invoke(nucypher_cli,
                                 divide_args,
                                 catch_exceptions=False,
                                 env=dict(NUCYPHER_KEYRING_PASSWORD=INSECURE_DEVELOPMENT_PASSWORD))
    assert result.exit_code == 0

    stake_args = ('stake', 'list',
                  '--config-file', configuration_file_location,
                  '--poa')

    user_input = f'{INSECURE_DEVELOPMENT_PASSWORD}'
    result = click_runner.invoke(nucypher_cli, stake_args, input=user_input, catch_exceptions=False)
    assert result.exit_code == 0
    assert str(NU(token_economics.minimum_allowed_locked, 'NuNit').to_tokens()) in result.output
