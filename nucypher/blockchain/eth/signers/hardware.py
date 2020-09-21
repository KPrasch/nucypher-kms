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

import rlp
import struct
import trezorlib
from eth_account._utils.transactions import (
    assert_valid_fields,
    Transaction,
    serializable_unsigned_transaction_from_dict
)
from eth_utils.address import to_canonical_address
from eth_utils.applicators import apply_key_map
from eth_utils.conversions import to_int
from functools import wraps
from hexbytes import HexBytes
from ledgerblue import getDongle
from ledgerblue.comm import getDongle
from ledgerblue.commException import CommException
from trezorlib import ethereum
from trezorlib.client import get_default_client
from trezorlib.tools import parse_path, Address, H_
from trezorlib.transport import TransportException
from typing import List, Tuple, Union, Dict, Callable
from web3 import Web3

from nucypher.blockchain.eth.signers.base import HardwareWallet


def handle_trezor_call(device_func) -> Callable:
    """Decorator for calls to trezorlib that require physical device interactions."""
    @wraps(device_func)
    def wrapped(trezor, *args, **kwargs):
        import usb1  # may not be installable on some systems (consider CI)
        try:
            result = device_func(trezor, *args, **kwargs)
        except usb1.USBErrorNoDevice:
            error = "Nucypher cannot communicate to the TREZOR USB device. Was it disconnected?"
            raise trezor.NoDeviceDetected(error)
        except usb1.USBErrorBusy:
            raise trezor.DeviceError("The TREZOR USB device is busy.")
        else:
            return result
    return wrapped


def handle_ledger_call(device_func) -> Callable:
    """Decorator for calls to ledgerblue that require physical device interactions."""
    @wraps(device_func)
    def wrapped(ledger, *args, **kwargs):
        try:
            result = device_func(ledger, *args, **kwargs)
        except (OSError, CommException):
            error = "Nucypher cannot communicate to the ledger USB device. Was it disconnected?"
            raise ledger.NoDeviceDetected(error)
        else:
            return result
    return wrapped


class TrezorSigner(HardwareWallet):
    """A trezor message and transaction signing client."""

    def __init__(self):
        try:
            self.__client = get_default_client()
        except TransportException:
            raise self.NoDeviceDetected("Could not find a TREZOR device to connect to. Have you unlocked it?")
        self._device_id = self.__client.get_device_id()
        self.__addresses = dict()  # track derived addresses
        self.__load_addresses()

    @classmethod
    def uri_scheme(cls) -> str:
        return 'trezor'

    #
    # Internal
    #

    def __get_address_path(self, index: int = None, checksum_address: str = None) -> List[H_]:
        """Resolves a checksum address into an HD path and returns it."""
        if index is not None and checksum_address:
            raise ValueError("Expected index or checksum address; Got both.")
        elif index is not None:
            hd_path = parse_path(f"{self.DERIVATION_ROOT}/{index}")
        else:
            try:
                hd_path = self.__addresses[checksum_address]
            except KeyError:
                raise RuntimeError(f"{checksum_address} was not loaded into the device address cache.")
        return hd_path

    @handle_trezor_call
    def __get_address(self, index: int = None, hd_path: Address = None, show_display: bool = True) -> str:
        """Resolves a trezorlib HD path into a checksum address and returns it."""
        if not hd_path:
            if index is None:
                raise ValueError("No index or HD path supplied.")  # TODO: better error handling here
            hd_path = self.__get_address_path(index=index)
        address = ethereum.get_address(client=self.__client, n=hd_path, show_display=show_display)
        return address

    def __load_addresses(self) -> None:
        """
        Derive trezor addresses up to ADDRESS_CACHE_SIZE relative to
        the calculated base path and internally cache them.
        """
        for index in range(self.ADDRESS_CACHE_SIZE):
            hd_path = self.__get_address_path(index=index)
            address = self.__get_address(hd_path=hd_path, show_display=False)
            self.__addresses[address] = hd_path

    @staticmethod
    def _format_transaction(transaction_dict: dict) -> dict:
        """
        Handle Web3.py -> Trezor native transaction field formatting
        # https://web3py.readthedocs.io/en/latest/web3.eth.html#web3.eth.Eth.sendRawTransaction
        """
        assert_valid_fields(transaction_dict)
        trezor_transaction_keys = {'gas': 'gas_limit', 'gasPrice': 'gas_price', 'chainId': 'chain_id'}
        trezor_transaction = dict(apply_key_map(trezor_transaction_keys, transaction_dict))
        return trezor_transaction

    @handle_trezor_call
    def __sign_transaction(self, n: List[int], trezor_transaction: dict) -> Tuple[bytes, bytes, bytes]:
        """Internal wrapper for trezorlib transaction signing calls"""
        v, r, s = trezorlib.ethereum.sign_tx(client=self.__client, n=n, **trezor_transaction)
        return v, r, s

    #
    # Trezor Signer API
    #

    @classmethod
    def from_signer_uri(cls, uri: str) -> 'TrezorSigner':
        """Return a trezor signer from URI string i.e. trezor:///my/trezor/path """
        if uri != cls.uri_scheme():  # TODO: #2269 Support "rich URIs" for trezors
            raise cls.InvalidSignerURI(f'{uri} is not a valid trezor URI scheme')
        return cls()

    @property
    def accounts(self) -> List[str]:
        """Returns a list of cached trezor checksum addresses from initial derivation."""
        return list(self.__addresses.keys())

    @handle_trezor_call
    def sign_message(self, message: bytes, checksum_address: str) -> HexBytes:
        """
        Signs a message via the TREZOR ethereum sign_message API and returns
        a named tuple containing the signature and the address used to sign it.
        This method requires interaction between the TREZOR and the user.
        """
        # TODO: #2262 Implement Trezor Message Signing
        hd_path = self.__get_address_path(checksum_address=checksum_address)
        signed_message = trezorlib.ethereum.sign_message(self.__client, hd_path, message)
        return HexBytes(signed_message.signature)

    def sign_transaction(self,
                         transaction_dict: dict,
                         rlp_encoded: bool = True
                         ) -> Union[HexBytes, Transaction]:
        """
        Sign a transaction with a trezor hardware wallet.

        This method handles transaction validation, field formatting, signing,
        and outgoing serialization.  Accepts a standard transaction dictionary as input,
        and produces an RLP encoded raw signed transaction by default.

        Internally the standard transaction dictionary is reformatted for trezor API consumption
        via calls `trezorlib.client.ethereum.sign_tx`.

        WARNING: This function returns a raw signed transaction which can be
        broadcast by anyone with a connection to the ethereum network.

        ***Treat pre-signed raw transactions produced by this function like money.***

        """

        # Consume the sender inside the transaction request's 'from field.
        checksum_address = transaction_dict.pop('from')

        # Format contract data field for both trezor and eth_account's Transaction
        if transaction_dict.get('data') is not None:  # empty string is valid
            transaction_dict['data'] = Web3.toBytes(HexBytes(transaction_dict['data']))

        # Format transaction fields for Trezor, Lookup HD path, and Sign Transaction
        # Leave the chain ID in tact for the trezor signing request:
        # If `chain_id` is included, an EIP-155 transaction signature will be applied
        # https://github.com/trezor/trezor-core/pull/311
        if 'chainId' not in transaction_dict:
            raise self.SignerError(
                'Invalid EIP-155 transaction - "chain_id" field is missing in trezor signing request.')

        trezor_transaction = self._format_transaction(transaction_dict=transaction_dict)
        n = self.__get_address_path(checksum_address=checksum_address)
        _v, _r, _s = self.__sign_transaction(n=n, trezor_transaction=trezor_transaction)

        # Format the transaction for eth_account Transaction consumption
        # ChainID is longer needed since it is later derived with v = (v + 2) * (chain_id + 35)
        # see https://github.com/ethereum/eips/issues/155
        del transaction_dict['chainId']
        transaction_dict['to'] = to_canonical_address(checksum_address)  # str -> bytes

        # Create RLP serializable Transaction instance with eth_account
        signed_transaction = Transaction(v=to_int(_v),  # int
                                         r=to_int(_r),  # bytes -> int
                                         s=to_int(_s),  # bytes -> int
                                         **transaction_dict)

        # Optionally encode as RLP for broadcasting
        if rlp_encoded:
            signed_transaction = HexBytes(rlp.encode(signed_transaction))

        return signed_transaction


class LedgerSigner(HardwareWallet):
    """
    A ledger message and transaction signing client.

    Big thanks to @kayagoban for their "shadowlands" implementation &
    showing python authors the way to use ledger like geth does.

    Citations and References
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    - https://github.com/kayagoban/shadowlands/blob/master/shadowlands/credstick/ledger_ethdriver.py
    - https://gist.github.com/bargst/5f896e4a5984593d43f1b4eb66f79d68
    - https://github.com/LedgerHQ/blue-app-eth/blob/master/doc/ethapp.asc


    The transaction signing protocol is defined as follows:
       CLA | INS | P1 | P2 | Lc  | Le
       ----+-----+----+----+-----+---
        E0 | 04  | 00: first transaction data block
                   80: subsequent transaction data block
                      | 00 | variable | variable

    Where the input for the first transaction block (first 255 bytes) is:

    Description                                      | Length
    -------------------------------------------------+----------
    Number of BIP 32 derivations to perform (max 10) | 1 byte
    First derivation index (big endian)              | 4 bytes
    ...                                              | 4 bytes
    Last derivation index (big endian)               | 4 bytes
    RLP transaction chunk                            | arbitrary

    """

    # Ethereum ledger app opcodes
    CLA = b'\xe0'
    INS_OPCODE_GET_ADDRESS = b'\x02'
    INS_OPCODE_SIGN_TRANS = b'\x04'
    INS_OPCODE_GET_VERSION = b'\x06'

    # get address protocol
    P1_RETURN_ADDRESS = b'\x00'
    P1_RETURN_AND_VERIFY_ADDRESS = b'\x01'
    P2_NO_CHAIN_CODE = b'\x00'
    P2_RETURN_CHAIN_CODE = b'\x01'

    # transaction protocol
    P1_FIRST_TRANS_DATA_BLOCK = b'\x00'
    P1_SUBSEQUENT_TRANS_DATA_BLOCK = b'\x80'
    P2_UNUSED_PARAMETER = b'\x00'
    P2_UNUSED_PARAMETER2 = b'\x01'

    @handle_ledger_call
    def __init__(self):
        self.dongle = getDongle(debug=False)

    @classmethod
    def uri_scheme(cls) -> str:
        return 'ledger'

    @classmethod
    @handle_ledger_call
    def open(cls):
        # getDongle(True) forces verification of the user address on the device.
        cls._driver = getDongle(False)
        cls.manufacturerStr = cls._driver.device.get_manufacturer_string()
        cls.productStr = cls._driver.device.get_product_string()

    @handle_ledger_call
    def close(self):
        self.dongle.device.close()
        self.dongle = None

    @handle_ledger_call
    def version(self):
        apdu = b'\xe0\x06\x00\x00\x00\x04'
        result = self.dongle.exchange(apdu)
        return result

    def _parse_bip32_path(self, offset):
        """
        Convert an offset to a bytes payload to be sent to the ledger
        representing bip32 derivation path.
        """
        path = self.DERIVATION_ROOT + str(offset)
        result = bytes()
        elements = path.split('/')
        for pathElement in elements:
            element = pathElement.split("'")
            if len(element) == 1:
                result = result + struct.pack(">I", int(element[0]))
            else:
                result = result + struct.pack(">I", 0x80000000 | int(element[0]))
        return result

    @staticmethod
    def encode_path(hd_path: str):
        result = b''
        if len(hd_path) == 0:
            return result
        elements = hd_path.split('/')
        for pathElement in elements:
            element = pathElement.split('\'')
            if len(element) == 1:
                result = result + struct.pack(">I", int(element[0]))
            else:
                result = result + struct.pack(">I", 0x80000000 | int(element[0]))
        return result

    def __get_address_path(self, index: int = None, checksum_address: str = None):
        """Resolves a checksum address into an HD path and returns it."""
        if index is not None and checksum_address:
            raise ValueError("Expected index or checksum address; Got both.")
        elif index is not None:
            hd_path = self._parse_bip32_path(f"{self.DERIVATION_ROOT}/{index}")
        else:
            try:
                hd_path = self.__addresses[checksum_address]
            except KeyError:
                raise RuntimeError(f"{checksum_address} was not loaded into the device address cache.")
        return hd_path

    @property
    def accounts(self, limit=5, page=0):
        """List Ethereum HD wallet address of the ledger device"""
        return list(map(lambda offset: self.get_address(offset), range(page * limit, (page + 1) * limit)))

    def sign_message(self, account: str, message: bytes, **kwargs) -> HexBytes:
        return NotImplemented  # TODO: Implement message signing for the ledger

    @handle_ledger_call
    def sign_transaction(self, transaction_dict: Dict, rlp_encoded: bool = True):

        # Consume the sender inside the transaction request's 'from field.
        sender = transaction_dict.pop('from')
        tx = serializable_unsigned_transaction_from_dict(transaction_dict)
        encodedTx = rlp.encode(tx)

        # Resolve the sender address into an HD path on the ledger.
        hd_path = self.__get_address_path(checksum_address=sender)
        encodedPath = self.encode_path(hd_path)

        # Each path element is 4 bytes.  How many path elements are we sending?
        derivationPathCount = (len(encodedPath) // 4).to_bytes(1, 'big')

        # Prepend the byte representing the count of path elements to the path encoding itself.
        encodedPath = derivationPathCount + encodedPath
        dataPayload = encodedPath + encodedTx

        # Big thanks to the Geth team for their ledger implementation (and documentation).
        # To the others reading, the ledger can only take 255 bytes of data payload per apdu exchange.
        # hence, you have to chunk and use 0x08 for the P1 opcode on subsequent calls.

        p1_op = self.P1_FIRST_TRANS_DATA_BLOCK
        while len(dataPayload) > 0:
            chunk_size = 255
            if chunk_size > len(dataPayload):
                chunk_size = len(dataPayload)

            encodedChunkSize = chunk_size.to_bytes(1, 'big')
            apdu = self.CLA                     \
                   + self.INS_OPCODE_SIGN_TRANS \
                   + p1_op                      \
                   + self.P2_UNUSED_PARAMETER   \
                   + encodedChunkSize           \
                   + dataPayload[:chunk_size]

            result = self.dongle.exchange(apdu)  # <-- Ledger
            dataPayload = dataPayload[chunk_size:]
            p1_op = self.P1_SUBSEQUENT_TRANS_DATA_BLOCK

            _v = result[0]
            _r = int((result[1:1 + 32]).hex(), 16)
            _s = int((result[1 + 32: 1 + 32 + 32]).hex(), 16)

        # Create RLP serializable Transaction instance with eth_account
        signed_transaction = Transaction(v=to_int(_v),
                                         r=to_int(_r),
                                         s=to_int(_s),
                                         **transaction_dict)

        # Optionally encode as RLP for broadcasting
        if rlp_encoded:
            signed_transaction = HexBytes(rlp.encode(signed_transaction))

        return signed_transaction
