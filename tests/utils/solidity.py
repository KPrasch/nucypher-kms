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


from typing import Callable, Type, List
from web3 import Web3

from nucypher.types import Agent


def to_bytes32(value=None, hexstr=None) -> bytes:
    return Web3.toBytes(primitive=value, hexstr=hexstr).rjust(32, b'\0')


def to_32byte_hex(value=None, hexstr=None) -> str:
    return Web3.toHex(to_bytes32(value=value, hexstr=hexstr))


def get_mapping_entry_location(key: bytes, mapping_location: int) -> int:
    if not(isinstance(key, bytes) and len(key) == 32):
        raise ValueError("Mapping key must be a 32-long bytestring")
    # See https://solidity.readthedocs.io/en/latest/internals/layout_in_storage.html#mappings-and-dynamic-arrays
    entry_location = Web3.toInt(Web3.keccak(key + mapping_location.to_bytes(32, "big")))
    return entry_location


def get_array_data_location(array_location: int) -> int:
    # See https://solidity.readthedocs.io/en/latest/internals/layout_in_storage.html#mappings-and-dynamic-arrays
    data_location = Web3.toInt(Web3.keccak(to_bytes32(array_location)))
    return data_location


COLLECTION_MARKER = "contract_api"  # decorator attribute


def __is_contract_method(agent_class: Type[Agent], method_name: str) -> bool:
    method_or_property = getattr(agent_class, method_name)
    try:
        real_method: Callable = method_or_property.fget  # Property (getter)
    except AttributeError:
        real_method: Callable = method_or_property  # Method
    contract_api: bool = hasattr(real_method, COLLECTION_MARKER)
    return contract_api


def collect_agent_api(agent_class: Type[Agent]) -> List[Callable]:
    agent_attrs = dir(agent_class)
    predicate = __is_contract_method
    methods = list(getattr(agent_class, name) for name in agent_attrs if predicate(agent_class, name))
    return methods
