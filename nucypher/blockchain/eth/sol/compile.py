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

from os.path import abspath, dirname

import itertools
import os
import re
from solcx.main import compile_standard
from twisted.logger import Logger
from typing import List, NamedTuple, Optional, Set, ChainMap

from nucypher.blockchain.eth.sol import SOLIDITY_COMPILER_VERSION


class SourceDirs(NamedTuple):
    root_source_dir: str
    other_source_dirs: Optional[Set[str]] = None


class SolidityCompiler:

    __default_contract_version = 'v0.0.0'
    __default_contract_dir = os.path.join(dirname(abspath(__file__)), 'source')

    __compiled_contracts_dir = 'contracts'
    __zeppelin_library_dir = 'zeppelin'
    __aragon_library_dir = 'aragon'

    optimization_runs = 200

    class CompilerError(Exception):
        pass

    class VersionError(Exception):
        pass

    @classmethod
    def default_contract_dir(cls):
        return cls.__default_contract_dir

    def __init__(self,
                 source_dirs: List[SourceDirs] = None,
                 ignore_solidity_check: bool = False
                 ) -> None:

        # Allow for optional installation
        from solcx.install import get_executable

        self.log = Logger('solidity-compiler')

        version = SOLIDITY_COMPILER_VERSION if not ignore_solidity_check else None
        self.__sol_binary_path = get_executable(version=version)

        if source_dirs is None or len(source_dirs) == 0:
            self.source_dirs = [SourceDirs(root_source_dir=self.__default_contract_dir)]
        else:
            self.source_dirs = source_dirs

    def compile(self, include_ast: bool = True) -> dict:
        interfaces = dict()
        for root_source_dir, other_source_dirs in self.source_dirs:
            if root_source_dir is None:
                self.log.warn("One of the root directories is None")
                continue

            compile_result = self._compile(root_source_dir, other_source_dirs)
            compiled_contracts = compile_result['contracts'].items()
            compiled_sources = compile_result['sources'].items()

            for (source_path, source_data), (contract_path, bundle) in zip(compiled_sources, compiled_contracts):
                for exported_name, contract_data in bundle.items():
                    # Extract contract version from docs
                    version_search = re.search(r"""
                    
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
                    
                    """, contract_data['metadata'], re.VERBOSE)  # FIXME: No!!!
                    version = version_search.group(1) if version_search else self.__default_contract_version

                    if include_ast:
                        # pack it up pack it in
                        ast = source_data['ast']
                        contract_data['ast'] = ast

                    try:
                        existence_data = interfaces[exported_name]
                    except KeyError:
                        existence_data = dict()
                        interfaces.update({exported_name: existence_data})
                    if version not in existence_data:
                        existence_data.update({version: contract_data})

        return interfaces

    def collect_sources(self, root_source_dir: str, other_source_dirs: [str]):

        self.log.info("Using solidity compiler binary at {}".format(self.__sol_binary_path))
        contracts_dir = os.path.join(root_source_dir, self.__compiled_contracts_dir)
        self.log.info("Compiling solidity source files at {}".format(contracts_dir))

        source_paths = dict()
        source_walker = os.walk(top=contracts_dir, topdown=True)
        if other_source_dirs is not None:
            for source_dir in other_source_dirs:
                other_source_walker = os.walk(top=source_dir, topdown=True)
                source_walker = itertools.chain(source_walker, other_source_walker)

        for root, dirs, files in source_walker:
            for filename in files:
                if filename.endswith('.sol') and 'Abstract' not in filename and "Interface" not in filename:
                    path = os.path.join(root, filename)
                    source_paths[filename] = dict(urls=[path])
                    self.log.debug("Collecting solidity source {}".format(path))

        # Compile with remappings: https://github.com/ethereum/py-solc
        zeppelin_dir = os.path.join(root_source_dir, self.__zeppelin_library_dir)
        aragon_dir = os.path.join(root_source_dir, self.__aragon_library_dir)

        remappings = (
            "contracts={}".format(contracts_dir),
            "zeppelin={}".format(zeppelin_dir),
            "aragon={}".format(aragon_dir),
        )

        return source_paths, remappings

    def _compile(self, root_source_dir: str, other_source_dirs: [str], ast: bool = True) -> dict:
        """Executes the compiler with parameters specified in the json config"""

        # Allow for optional installation
        from solcx.exceptions import SolcError

        source_paths, remappings = self.collect_sources(root_source_dir=root_source_dir, other_source_dirs=other_source_dirs)
        self.log.info(f"Compiling with import remappings {', '.join(remappings)}")

        try:

            # Standard JSON I/O Compile
            contract_outputs = [
                "metadata",  # TODO: FOR THE LOVE OF GOD
                "devdoc",
                "userdoc",
                "abi",
                "evm.bytecode",
                "evm.bytecode.sourceMap"
            ]

            file_outputs = []
            if ast:
                file_outputs.append('ast')

            # TODO: No strings!!!
            config = {
                "language": "Solidity",
                "sources": source_paths,
                "settings": {
                    "remappings": list(remappings),
                    "optimizer": {
                        "enabled": True,
                        "runs": self.optimization_runs
                    },
                    "evmVersion": "berlin",
                    "outputSelection": {
                        "*": {
                            "*": contract_outputs,
                            "": file_outputs
                        }
                    }
                }
            }

            compiled_sol = compile_standard(input_data=config,
                                            allow_paths=root_source_dir)

            self.log.info(f"Successfully compiled {len(compiled_sol)} contracts with {self.optimization_runs} optimization runs")

        except FileNotFoundError:
            raise RuntimeError("The solidity compiler is not at the specified path. "
                               "Check that the file exists and is executable.")
        except PermissionError:
            raise RuntimeError("The solidity compiler binary at {} is not executable. "
                               "Check the file's permissions.".format(self.__sol_binary_path))

        except SolcError:
            raise

        return compiled_sol
