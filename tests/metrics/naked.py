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

from collections import Counter

import click
import solcast
from typing import Type

from nucypher.blockchain.eth.agents import (
    NucypherTokenAgent,
    StakingEscrowAgent,
    PolicyManagerAgent,
    PreallocationEscrowAgent,
    AdjudicatorAgent,
    MultiSigAgent,
    WorkLockAgent
)
from nucypher.blockchain.eth.sol.compile import SolidityCompiler
from nucypher.types import Agent
from tests.utils.solidity import collect_contract_api

AGENTS = (
    NucypherTokenAgent,
    StakingEscrowAgent,
    PolicyManagerAgent,
    PreallocationEscrowAgent,
    AdjudicatorAgent,
    WorkLockAgent,
    MultiSigAgent
)


def get_exposed_contract_interfaces(agent_class: Type[Agent]):

    compiler = SolidityCompiler()
    compiled_contracts = compiler.compile(include_ast=True)

    # Get compiled contracts and metadata
    contract_versions = compiled_contracts[agent_class.registry_contract_name]
    latest_version, contract_data = list(contract_versions.items())[-1]  # TODO: Better way to get last version
    ast = contract_data['ast']

    # Parse AST
    nodes = solcast.from_ast(ast)
    external_functions = nodes.children(
        include_children=False,
        filters={'nodeType': "FunctionDefinition", "visibility": "external"}
    )
    public_functions = nodes.children(
        include_children=False,
        filters={'nodeType': "FunctionDefinition", "visibility": "public"}
    )
    # filters = {'nodeType': "FunctionCall", "expression.name": "require"}

    exposed_contract_interfaces = (*external_functions, *public_functions)
    return exposed_contract_interfaces


def analyze(contract_api, agent_api):

    calls = Counter()
    for contract_function in contract_api:
        name = contract_function.name
        calls[name] = 0

    for agent_method in agent_api:

        # Handle
        try:
            # TODO: #2022: This might be a method also decorated @property
            # Get the inner function of the property
            agent_method = agent_method.fget  # Handle properties
        except AttributeError:
            pass

        cells = agent_method.__closure__
        for cell in cells:
            if not callable(cell.cell_contents):
                continue
            internal_names = cell.cell_contents.__code__.co_names
            contract_calls = tuple(call for call in internal_names if call in calls)
            for call in contract_calls:
                calls[call] += 1

    fallback_function_detected = '' in calls
    if fallback_function_detected:
        del calls['']  # Does not get explicit exposure

    return calls


def calculate_exposure(data: Counter) -> float:
    try:
        exposure = sum(1 for v in data.values() if v > 0) / len(data)
    except ZeroDivisionError:
        exposure = 0
    exposure *= 100
    exposure = round(exposure, 1)
    return exposure


def report(contract_name: str, exposure: float, data: Counter) -> None:
    click.secho(f'\n\n{contract_name} AGENT EXPOSURE {exposure}%\n=====================', fg='blue', bold=True)

    colors = {True: 'green', False: 'yellow'}
    for name, call_count in data.items():
        click.secho(f'{name}({call_count})', fg=colors[bool(call_count)])

    # TODO: JSON Output
    # print(json.dumps(data, indent=4))


def measure_contract_exposure():

    for agent_class in AGENTS:

        # Collect contract API
        exposed_contract_interfaces = get_exposed_contract_interfaces(agent_class=agent_class)

        # Collect Python API
        agent_api = collect_contract_api(agent_class=agent_class)

        # Analyze Exposure
        calls = analyze(contract_api=exposed_contract_interfaces, agent_api=agent_api)
        exposure = calculate_exposure(data=calls)
        report(contract_name=agent_class.registry_contract_name, exposure=exposure, data=calls)


if __name__ == '__main__':
    click.clear()
    measure_contract_exposure()
