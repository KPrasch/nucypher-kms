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


__all__ = ('compile_nucypher', )

import itertools
import os
import re
from pathlib import Path
from twisted.logger import Logger
from typing import Dict, Iterator, List, Optional, Tuple, Union

from nucypher.blockchain.eth.sol import SOLIDITY_COMPILER_VERSION as SOURCE_VERSION
from nucypher.exceptions import DevelopmentInstallationRequired

CompiledContracts = Dict[str, Dict[str, List[Dict[str, Union[str, List[Dict[str, str]]]]]]]

LOG = Logger('solidity-compiler')

DEFAULT_CONTRACT_VERSION: str = 'v0.0.0'
SOURCE_ROOT: Path = Path(__file__).parent / 'source'

CONTRACTS: str = 'contracts'
NUCYPHER_CONTRACTS_DIR: Path = SOURCE_ROOT / CONTRACTS

# Third Party Contracts
ZEPPELIN: str = 'zeppelin'
ARAGON: str = 'aragon'
ZEPPELIN_DIR: Path = SOURCE_ROOT / ZEPPELIN
ARAGON_DIR: Path = SOURCE_ROOT / ARAGON


SOURCES: List[str] = [
    str(NUCYPHER_CONTRACTS_DIR.resolve(strict=True))
]

ALLOWED_PATHS: List[str] = [
    str(SOURCE_ROOT.resolve(strict=True))
]

IGNORE_CONTRACT_PREFIXES: Tuple[str, ...] = (
    'Abstract',
    'Interface'
)


#
# Standard "JSON I/O" Compiler Config
# https://solidity.readthedocs.io/en/latest/using-the-compiler.html#input-description
#

OPTIMIZER: bool = True
OPTIMIZATION_RUNS: int = 200
LANGUAGE: str = 'Solidity'
EVMVERSION: str = 'berlin'
CONTRACT_OUTPUTS: List[str] = [

    # Active
    'abi',                     # ABI
    'devdoc',                  # Developer documentation (natspec)
    'userdoc',                 # User documentation (natspec)
    'evm.bytecode.object',     # Bytecode object

    # Inactive
    # 'metadata',                # Metadata
    # 'ir',                      # Yul intermediate representation of the code before optimization
    # 'irOptimized',             # Intermediate representation after optimization
    # 'storageLayout',           # Slots, offsets and types of the contract's state variables.
    # 'evm.assembly',            # New assembly format
    # 'evm.legacyAssembly',      # Old-style assembly format in JSON
    # 'evm.bytecode.opcodes',    # Opcodes list
    # 'evm.bytecode.linkReferences',  # Link references (if unlinked object)
    # 'evm.deployedBytecode',         # Deployed bytecode (has all the options that evm.bytecode has)
    # 'evm.deployedBytecode.immutableReferences', # Map from AST ids to bytecode ranges that reference immutables
    # 'evm.methodIdentifiers',        # The list of function hashes
    # 'evm.gasEstimates',             # Function gas estimates

]

# Compile with remappings: https://github.com/ethereum/py-solc
IMPORT_REMAPPINGS: List[str] = [
    f"{CONTRACTS}={NUCYPHER_CONTRACTS_DIR.resolve()}",
    f"{ZEPPELIN}={ZEPPELIN_DIR.resolve()}",
    f"{ARAGON}={ARAGON_DIR.resolve()}",
]

FILE_OUTPUTS: List[str] = []

COMPILER_SETTINGS: Dict = dict(
    remappings=IMPORT_REMAPPINGS,
    optimizer=dict(enabled=OPTIMIZER, runs=OPTIMIZATION_RUNS),
    evmVersion=EVMVERSION,
    outputSelection={"*": {"*": CONTRACT_OUTPUTS, "": FILE_OUTPUTS}}
)


class CompilerConfiguration(Dict):
    language: str
    sources: Dict[str, Dict[str, str]]
    settings: Dict


COMPILER_CONFIG = CompilerConfiguration(
    language=LANGUAGE,
    sources=SOURCES,
    settings=COMPILER_SETTINGS
)


def __source_filter(filename: str) -> bool:
    contains_ignored_prefix = any(prefix in filename for prefix in IGNORE_CONTRACT_PREFIXES)
    is_solidity_file = filename.endswith('.sol')
    return is_solidity_file and not contains_ignored_prefix


def __collect_sources(test_contracts: bool, source_dirs: Optional[Path] = None):

    # Default
    if not source_dirs:
        source_dirs: List[Path] = [SOURCE_ROOT / CONTRACTS]

    # Add test contracts to sources
    if test_contracts:
        from tests.constants import TEST_CONTRACTS_DIR
        source_dirs.append(TEST_CONTRACTS_DIR)

    # Collect all source directories
    source_paths = dict()
    for source_dir in source_dirs:
        source_walker = os.walk(top=str(source_dir), topdown=True)
        # Collect single directory
        for root, dirs, files in source_walker:
            # Collect files in source dir
            for filename in filter(__source_filter, files):
                path = os.path.join(root, filename)
                source_paths[filename] = dict(urls=[path])
                LOG.debug(f"Collecting solidity source {path}")
        LOG.info(f"Collected {len(source_paths)} solidity source files at {source_dir}")
    return source_paths


def _compile(source_dirs: Tuple[Path, ...] = None,
             include_ast: bool = True,
             ignore_version_check: bool = False,
             test_contracts: bool = False) -> dict:
    """Executes the compiler with parameters specified in the json config"""

    try:
        from solcx.install import get_executable
        from solcx.main import compile_standard
    except ImportError:
        raise DevelopmentInstallationRequired(importable_name='solcx')

    # Solidity Compiler Binary
    compiler_version = SOURCE_VERSION if not ignore_version_check else None
    solc_binary_path = get_executable(version=compiler_version)

    # Compile options
    if include_ast:
        FILE_OUTPUTS.append('ast')

    if test_contracts:
        from tests.constants import TEST_CONTRACTS_DIR
        ALLOWED_PATHS.append(str(TEST_CONTRACTS_DIR.resolve(True)))

    if source_dirs:
        for source in source_dirs:
            ALLOWED_PATHS.append(str(source.resolve(strict=True)))

    # Resolve Sources
    allowed_paths = ','.join(ALLOWED_PATHS)
    sources = __collect_sources(source_dirs=source_dirs, test_contracts=test_contracts)
    COMPILER_CONFIG.update(dict(sources=sources))

    try:
        LOG.info(f"Compiling with import remappings {' '.join(IMPORT_REMAPPINGS)}")
        compiled_sol = compile_standard(input_data=COMPILER_CONFIG, allow_paths=allowed_paths)
        LOG.info(f"Successfully compiled {len(compiled_sol)} contracts with {OPTIMIZATION_RUNS} optimization runs")
    except FileNotFoundError:
        raise RuntimeError("The solidity compiler is not at the specified path. "
                           "Check that the file exists and is executable.")
    except PermissionError:
        raise RuntimeError("The solidity compiler binary at {} is not executable. "
                           "Check the file's permissions.".format(solc_binary_path))
    return compiled_sol


def extract_version(contract_data: dict) -> str:
    try:
        devdoc = contract_data['devdoc']['details']
    except KeyError:
        return DEFAULT_CONTRACT_VERSION
    version_match = re.search(r"""
    \"details\":  # @dev tag in contract docs
    \".*?         # Skip any data in the beginning of details
    \|            # Beginning of version definition |
    (v            # Capture version starting from symbol v
    \d+           # At least one digit of major version
    \.            # Digits splitter
    \d+           # At least one digit of minor version
    \.            # Digits splitter
    \d+           # At least one digit of patch
    )             # End of capturing
    \|            # End of version definition |
    .*?\"         # Skip any data in the end of details
    """, devdoc, re.VERBOSE)
    version = version_match.group(1) if version_match else DEFAULT_CONTRACT_VERSION
    return version


def __handle_contract(contract_data: dict,
                      ast: bool,
                      source_data,
                      interfaces: dict,
                      exported_name: str,
                      ) -> None:
    if ast:
        # TODO: Sort AST by contract
        ast = source_data['ast']
        contract_data['ast'] = ast

    try:
        existence_data = interfaces[exported_name]
    except KeyError:
        existence_data = dict()
        interfaces.update({exported_name: existence_data})
    version = extract_version(contract_data=contract_data)
    if version not in existence_data:
        existence_data.update({version: contract_data})


def compile_nucypher(source_dirs: Optional[Tuple[Path, ...]] = None,
                     include_ast: bool = False,
                     ignore_version_check: bool = False,
                     test_contracts: bool = False
                     ) -> CompiledContracts:

    interfaces = dict()
    compile_result = _compile(include_ast=include_ast,
                              ignore_version_check=ignore_version_check,
                              test_contracts=test_contracts,
                              source_dirs=source_dirs)
    compiled_contracts, compiled_sources = compile_result['contracts'].items(), compile_result['sources'].items()
    for (source_path, source_data), (contract_path, compiled_contract) in zip(compiled_sources, compiled_contracts):
        for exported_name, contract_data in compiled_contract.items():
            __handle_contract(ast=include_ast,
                              contract_data=contract_data,
                              source_data=source_data,
                              interfaces=interfaces,
                              exported_name=exported_name)
    return interfaces
