import os

from nacl.exceptions import CryptoError

from nucypher.blockchain.eth.decorators import validate_checksum_address
from nucypher.config.constants import NUCYPHER_ENVVAR_KEYRING_PASSWORD
from nucypher.config.node import CharacterConfiguration


def get_password_from_prompt(prompt: str = "Enter password", envvar: str = '', confirm: bool = False) -> str:
    password = os.environ.get(envvar, NO_PASSWORD)
    if password is NO_PASSWORD:  # Collect password, prefer env var
        password = click.prompt(prompt, confirmation_prompt=confirm, hide_input=True)
    return password


def get_nucypher_password(confirm: bool = False, envvar=NUCYPHER_ENVVAR_KEYRING_PASSWORD) -> str:
    prompt = f"Enter NuCypher keyring password"
    if confirm:
        from nucypher.config.keyring import NucypherKeyring
        prompt += f" ({NucypherKeyring.MINIMUM_PASSWORD_LENGTH} character minimum)"
    keyring_password = get_password_from_prompt(prompt=prompt, confirm=confirm, envvar=envvar)
    return keyring_password


def unlock_nucypher_keyring(emitter, password: str, character_configuration: CharacterConfiguration):
    emitter.message(f'Decrypting {character_configuration._NAME} keyring...', color='yellow')
    if character_configuration.dev_mode:
        return True  # Dev accounts are always unlocked

    # NuCypher
    try:
        character_configuration.attach_keyring()
        character_configuration.keyring.unlock(password=password)  # Takes ~3 seconds, ~1GB Ram
    except CryptoError:
        raise character_configuration.keyring.AuthenticationFailed


@validate_checksum_address
def get_client_password(checksum_address: str, envvar: str = '') -> str:
    prompt = f"Enter password to unlock account {checksum_address}"
    client_password = get_password_from_prompt(prompt=prompt, envvar=envvar, confirm=False)
    return client_password