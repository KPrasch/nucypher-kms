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

from abc import ABC, abstractmethod, ABCMeta
from hexbytes.main import HexBytes
from typing import List
from urllib.parse import urlparse

from nucypher.blockchain.eth.decorators import validate_checksum_address
from nucypher.utilities.logging import Logger


class Signer(ABC):

    _SIGNERS = NotImplemented  # set dynamically in __init__.py

    log = Logger(__qualname__)

    class SignerError(Exception):
        """Base exception class for signer errors"""

    class InvalidSignerURI(SignerError):
        """Raised when an invalid signer URI is detected"""

    class AccountLocked(SignerError):
        def __init__(self, account: str):
            self.message = f'{account} is locked.'
            super().__init__(self.message)

    class UnknownAccount(SignerError):
        def __init__(self, account: str):
            self.message = f'Unknown account {account}.'
            super().__init__(self.message)

    @classmethod
    @abstractmethod
    def uri_scheme(cls) -> str:
        return NotImplemented

    @classmethod
    def from_signer_uri(cls, uri: str) -> 'Signer':
        parsed = urlparse(uri)
        scheme = parsed.scheme if parsed.scheme else parsed.path
        try:
            signer_class = cls._SIGNERS[scheme]
        except KeyError:
            # This block can be considered the "pass-through"
            # for providers to be used as external signers.
            try:
                from nucypher.blockchain.eth.signers.software import Web3Signer
                signer = Web3Signer.from_signer_uri(uri=uri)
            except cls.InvalidSignerURI:
                message = f'{uri} is not a valid signer URI.  Available schemes: {", ".join(cls._SIGNERS)}'
                raise cls.InvalidSignerURI(message)
            return signer
        signer = signer_class.from_signer_uri(uri=uri)
        return signer

    @abstractmethod
    def is_device(self, account: str) -> bool:
        """Some signing client support both software and hardware wallets,
        this method is implemented as a boolean to tell the difference."""
        return NotImplemented

    @property
    @abstractmethod
    def accounts(self) -> List[str]:
        return NotImplemented

    @abstractmethod
    def unlock_account(self, account: str, password: str, duration: int = None) -> bytes:
        return NotImplemented

    @abstractmethod
    def lock_account(self, account: str) -> str:
        return NotImplemented

    @abstractmethod
    def sign_transaction(self, transaction_dict: dict) -> HexBytes:
        return NotImplemented

    @abstractmethod
    def sign_message(self, account: str, message: bytes, **kwargs) -> HexBytes:
        return NotImplemented


class HDWallet(Signer, metaclass=ABCMeta):

    __BIP_44 = 44
    __ETH_COIN_TYPE = 60

    CHAIN_ID = 0  # 0 is mainnet
    DEFAULT_ACCOUNT = 0
    DEFAULT_ACCOUNT_INDEX = 0
    DERIVATION_ROOT = f"{__BIP_44}'/{__ETH_COIN_TYPE}'/{DEFAULT_ACCOUNT}'/{CHAIN_ID}"
    ADDRESS_CACHE_SIZE = 10  # default number of accounts to derive and internally track


class HardwareWallet(HDWallet, metaclass=ABCMeta):

    class DeviceError(Exception):
        """Base exception for trezor signing API"""

    class NoDeviceDetected(DeviceError):
        """Raised when an operation requires a device but none are available"""

    def is_device(self, account: str) -> bool:
        """Always a device."""
        return True

    @validate_checksum_address
    def unlock_account(self, account: str, password: str, duration: int = None) -> bool:
        """Defer account unlocking to the hardware, do not indicate application level unlocking logic."""
        return True

    @validate_checksum_address
    def lock_account(self, account: str) -> bool:
        """Defer account locking to the hardware, do not indicate application level unlocking logic."""
        return True
