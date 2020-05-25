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

import pytest
import solcast

from nucypher.blockchain.eth.agents import EthereumContractAgent
from tests.utils.solidity import collect_contract_api

AGENTS = tuple(EthereumContractAgent.__subclasses__())


@pytest.fixture(scope='module')
def compiled_contracts(solidity_compiler):
    compiled_contracts = solidity_compiler.compile()
    return compiled_contracts


@pytest.mark.parametrize('agent_class', AGENTS)
def test_agent_respects_contract(compiled_contracts, agent_class, mock_contract_agency):

    # Get compiled contracts and metadata
    contract_versions = compiled_contracts[agent_class.registry_contract_name]
    latest_version, contract_data = list(contract_versions.items())[-1]  # TODO: Better way to get last version
    ast = contract_data['ast']

    # Parse AST
    nodes = solcast.from_ast(ast)
    external_methods = nodes.children(
        include_children=False,
        filters={'nodeType': "FunctionDefinition", "visibility": "external"}
    )
    public_methods = nodes.children(
        include_children=False,
        filters={'nodeType': "FunctionDefinition", "visibility": "public"}
    )
    # filters = {'nodeType': "FunctionCall", "expression.name": "require"}

    # Collect Python API
    mock_agent = mock_contract_agency.get_agent(agent_class=agent_class)
    agent_api = collect_contract_api(agent_class=agent_class)

    pass
