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

import base64
import json
from pathlib import Path
from typing import Union, Optional, Dict, Callable

import constant_sorrow
import hashlib
import os
from bytestring_splitter import VariableLengthBytestring, BytestringKwargifier
from constant_sorrow.constants import ALICE, BOB, NO_SIGNATURE
from hexbytes.main import HexBytes
from umbral.keys import UmbralPublicKey

from nucypher.characters.base import Character
from nucypher.characters.lawful import Alice, Bob
from nucypher.config.constants import DEFAULT_CONFIG_ROOT
from nucypher.crypto.powers import SigningPower, DecryptingPower
from nucypher.policy.collections import TreasureMap


class Card:
    """"
    A simple serializable representation of a character's public materials.
    """

    _specification = dict(
        character_flag=(bytes, 8),
        verifying_key=(UmbralPublicKey, 33),
        encrypting_key=(UmbralPublicKey, 33),
        signature=(Signature, 64),
        nickname=(bytes, VariableLengthBytestring)
    )

    __FLAGS = {
        bytes(ALICE): Alice,
        bytes(BOB): Bob,
    }

    __MAX_NICKNAME_SIZE = 10
    __BASE_PAYLOAD_SIZE = sum(length[1] for length in _specification.values() if isinstance(length[1], int))
    __MAX_CARD_LENGTH = __BASE_PAYLOAD_SIZE + __MAX_NICKNAME_SIZE
    __FILE_EXTENSION = 'card'
    CARD_DIR = Path(DEFAULT_CONFIG_ROOT) / 'cards'

    class InvalidCard(Exception):
        """Raised when an invalid, corrupted, or otherwise unsable card is encountered"""

    class UnknownCard(Exception):
        """Raised when a card cannot be found in storage"""

    class UnsignedCard(Exception):
        """Raised when a card serialization cannot be handled due to the lack of a signature"""

    def __init__(self,
                 character_flag: Union[ALICE, BOB],
                 verifying_key: UmbralPublicKey,
                 encrypting_key: Optional[UmbralPublicKey] = None,
                 signature=NO_SIGNATURE,
                 card_dir: Path = CARD_DIR,
                 nickname: bytes = None):

        self.card_dir = card_dir
        try:
            self.__character_class = self.__FLAGS[bytes(character_flag)]
        except KeyError:
            raise ValueError(f'Unsupported card type {str(character_flag)}')
        self.__character_flag = character_flag
        self.__verifying_key = verifying_key    # signing public key
        self.__encrypting_key = encrypting_key  # public key
        self.__signature = signature
        self.__nickname = nickname
        self.__validate()

    def __repr__(self) -> str:
        name = self.nickname or f'{self.__character_class.__name__}'
        short_key = bytes(self.__verifying_key).hex()[:6]
        r = f'{self.__class__.__name__}({name}:{short_key}:{self.id.hex()[:6]})'
        return r

    def __eq__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            raise TypeError(f'Cannot compare {self.__class__.__name__} and {other}')
        return self.id == other.id

    def __validate(self) -> bool:
        if self.__nickname and (len(self.__nickname) > self.__MAX_NICKNAME_SIZE):
            raise self.InvalidCard(f'Nickname exceeds maximum length')
        if self.__signature is not NO_SIGNATURE:
            self.__signature.verify(verifying_key=self.__verifying_key, message=self.__payload)
        return True

    @staticmethod
    def __hash(payload: bytes) -> HexBytes:
        blake = hashlib.blake2b()
        blake.update(payload)
        digest = blake.digest().hex()
        return HexBytes(digest)

    #
    # Serializers
    #

    def __bytes__(self) -> bytes:
        if self.__signature is NO_SIGNATURE:
            raise self.UnsignedCard
        payload = self.__payload
        payload += bytes(self.__signature)
        if self.nickname:
            payload += VariableLengthBytestring(self.__nickname)
        return payload

    def __hex__(self) -> str:
        return self.to_hex()

    @property
    def __payload(self) -> bytes:
        elements = (
            self.__character_flag,
            self.__verifying_key,
            self.__encrypting_key,
        )
        card_bytes = b''.join(bytes(e) for e in elements)
        return card_bytes

    @classmethod
    def from_bytes(cls, card_bytes: bytes) -> 'Card':
        if len(card_bytes) > cls.__MAX_CARD_LENGTH:
            raise cls.InvalidCard(f'Card exceeds maximum size. Verify the card filepath and contents.')
        return BytestringKwargifier(cls, **cls._specification)(card_bytes)

    @classmethod
    def from_hex(cls, hexdata: str):
        return cls.from_bytes(bytes.fromhex(hexdata))

    def to_hex(self) -> str:
        return bytes(self).hex()

    @classmethod
    def from_base64(cls, b64data: str):
        return cls.from_bytes(base64.urlsafe_b64decode(b64data))

    def to_base64(self) -> str:
        return base64.urlsafe_b64encode(bytes(self)).decode()

    def to_qr_code(self):
        import qrcode
        from qrcode.main import QRCode
        qr = QRCode(
            version=1,
            box_size=1,
            border=4,  # min spec is 4
            error_correction=qrcode.constants.ERROR_CORRECT_L,
        )
        qr.add_data(bytes(self))
        qr.print_ascii()

    @classmethod
    def from_dict(cls, card: Dict):
        instance = cls(verifying_key=card['verifying_key'],
                       encrypting_key=card['encrypting_key'],
                       character_flag=card['character'])
        return instance

    def to_dict(self) -> Dict:
        payload = dict(
            verifying_key=self.verifying_key,
            encrypting_key=self.encrypting_key,
            character=self.__character_flag
        )
        return payload

    @classmethod
    def from_character(cls, character: Character) -> 'Card':
        flag = getattr(constant_sorrow.constants, character.__class__.__name__.upper())
        instance = cls(verifying_key=character.public_keys(power_up_class=SigningPower),
                       encrypting_key=character.public_keys(power_up_class=DecryptingPower),
                       character_flag=flag)
        instance.sign(signing_power=character._crypto_power.power_ups(SigningPower))
        return instance

    #
    # Card API
    #

    @property
    def verifying_key(self) -> UmbralPublicKey:
        return self.__verifying_key

    @property
    def encrypting_key(self) -> UmbralPublicKey:
        return self.__encrypting_key

    @property
    def id(self) -> HexBytes:
        return self.__hash(self.__payload)

    @property
    def nickname(self) -> str:
        if self.__nickname:
            return self.__nickname.decode()

    def set_nickname(self, nickname: str) -> None:
        if len(nickname.encode()) > self.__MAX_NICKNAME_SIZE:
            raise ValueError(f'New nickname exceeds maximum size ({self.__MAX_NICKNAME_SIZE} bytes)')
        self.__nickname = nickname.encode()

    @nickname.setter
    def nickname(self, nickname: str) -> None:
        self.set_nickname(nickname)

    def sign(self, signing_power: SigningPower) -> None:
        if signing_power.public_key() != self.__verifying_key:
            raise ValueError(f'Cannot sign card for another verifying key')
        if self.__signature is not NO_SIGNATURE:
            raise RuntimeError(f'Card already signed')
        self.__signature = signing_power.sign(self.__payload)

    #
    # Card Storage API
    #

    @property
    def is_saved(self) -> bool:
        filename = f'{self.id.hex()}.{self.__FILE_EXTENSION}'
        filepath = self.card_dir / filename
        exists = filepath.exists()
        return exists

    def save(self, encoder: Callable = base64.b64encode) -> Path:
        if not self.card_dir.exists():
            os.mkdir(str(self.card_dir))
        filename = f'{self.id.hex()}.{self.__FILE_EXTENSION}'
        filepath = self.card_dir / filename
        with open(str(filepath), 'w') as file:
            file.write(encoder(bytes(self)))
        return Path(filepath)

    @classmethod
    def load(cls,
             checksum: str,
             card_dir: Path = CARD_DIR,
             decoder: Callable = base64.b64decode
             ) -> 'Card':
        filename = f'{checksum}.{cls.__FILE_EXTENSION}'
        filepath = card_dir / filename
        try:
            with open(str(filepath), 'rb') as file:
                card_bytes = decoder(file.read())
        except FileNotFoundError:
            raise cls.UnknownCard
        instance = cls.from_bytes(card_bytes)
        return instance


class PolicyCredential:
    """
    A portable structure that contains information necessary for Alice or Bob
    to utilize the policy on the network that the credential describes.
    """

    def __init__(self, alice_verifying_key, label, expiration, policy_pubkey,
                 treasure_map=None):
        self.alice_verifying_key = alice_verifying_key
        self.label = label
        self.expiration = expiration
        self.policy_pubkey = policy_pubkey
        self.treasure_map = treasure_map

    def to_json(self):
        """
        Serializes the PolicyCredential to JSON.
        """
        cred_dict = {
            'alice_verifying_key': bytes(self.alice_verifying_key).hex(),
            'label': self.label.hex(),
            'expiration': self.expiration.iso8601(),
            'policy_pubkey': bytes(self.policy_pubkey).hex()
        }

        if self.treasure_map is not None:
            cred_dict['treasure_map'] = bytes(self.treasure_map).hex()

        return json.dumps(cred_dict)

    @classmethod
    def from_json(cls, data: str):
        """
        Deserializes the PolicyCredential from JSON.
        """
        cred_json = json.loads(data)

        alice_verifying_key = UmbralPublicKey.from_bytes(
                                    cred_json['alice_verifying_key'],
                                    decoder=bytes().fromhex)
        label = bytes().fromhex(cred_json['label'])
        expiration = maya.MayaDT.from_iso8601(cred_json['expiration'])
        policy_pubkey = UmbralPublicKey.from_bytes(
                            cred_json['policy_pubkey'],
                            decoder=bytes().fromhex)
        treasure_map = None

        if 'treasure_map' in cred_json:
            treasure_map = TreasureMap.from_bytes(
                                bytes().fromhex(cred_json['treasure_map']))

        return cls(alice_verifying_key, label, expiration, policy_pubkey,
                   treasure_map)

    def __eq__(self, other):
        return ((self.alice_verifying_key == other.alice_verifying_key) and
                (self.label == other.label) and
                (self.expiration == other.expiration) and
                (self.policy_pubkey == other.policy_pubkey))
