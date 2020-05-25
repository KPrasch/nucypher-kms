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
import inspect
import solcast
from typing import Type, Tuple, Dict, Callable, Iterable, List, Optional

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
from tests.utils.solidity import collect_agent_api

AGENTS = (
    NucypherTokenAgent,
    StakingEscrowAgent,
    PolicyManagerAgent,
    PreallocationEscrowAgent,
    AdjudicatorAgent,
    WorkLockAgent,
    MultiSigAgent
)


CONTRACTS: Optional[Dict[str, dict]] = None


def compile():
    global CONTRACTS
    compiler = SolidityCompiler()
    CONTRACTS = compiler.compile()


def compile_contract(agent_class, version: str):
    compiled_contract_versions = CONTRACTS[agent_class.contract_name]
    if version == 'latest':
        contract_versions = list(compiled_contract_versions.items())
        version_number, contract_data = contract_versions[-1]  # TODO: Better way to get last version
    else:
        version_number, contract_data = compiled_contract_versions[version]
    return contract_data


def scrape_ast(contract_data, visibility: str):
    ast = contract_data['ast']
    nodes = solcast.from_ast(ast)
    ast_functions = nodes.children(
        include_children=False,
        filters={'nodeType': "FunctionDefinition", "visibility": visibility}
    )
    # TODO: Follow-up idea - require coverage
    # filters = {'nodeType': "FunctionCall", "expression.name": "require"}
    return ast_functions


def get_exposed_contract_interfaces(agent_class: Type[Agent], version: str = 'latest'):
    contract_data = compile_contract(agent_class=agent_class, version=version)
    external_functions = scrape_ast(contract_data=contract_data, visibility='external')
    public_functions = scrape_ast(contract_data=contract_data, visibility='public')
    return external_functions, public_functions


def get_callable_cell_contents(agent_method: Callable) -> List[Callable]:
    if isinstance(agent_method, property):
        agent_method = agent_method.fget  # Handle properties
    members = inspect.getmembers(agent_method, inspect.isfunction)
    callable_cells = list()
    for member in members:
        callable_cells.extend([c for c in member if callable(c)])
    return callable_cells


def setup_function_counter(contract_api: Iterable[Callable]) -> Counter:

    # Initial state
    function_counter = Counter()
    for contract_function in contract_api:
        name = contract_function.name
        function_counter[name] = 0

    # Handle fallback functions
    fallback_function_detected = '' in function_counter
    if fallback_function_detected:
        del function_counter['']  # Does not get explicit exposure

    return function_counter


def sample(funcs: Iterable[Callable], function_counter: Counter) -> None:
    for func in funcs:
        internal_calls = inspect.getclosurevars(func)
        contract_calls = tuple(f for f in internal_calls.unbound if f in function_counter)
        for call in contract_calls:
            function_counter[call] += 1


def analyze(contract_api, agent_api) -> Counter:
    function_counter = setup_function_counter(contract_api=contract_api)
    for agent_method in agent_api:
        callable_code_cells = get_callable_cell_contents(agent_method=agent_method)
        sample(funcs=callable_code_cells, function_counter=function_counter)
    return function_counter


def calculate_exposure(data: Counter) -> float:
    try:
        exposure = sum(1 for v in data.values() if v > 0) / len(data)
    except ZeroDivisionError:
        exposure = 0
    exposure *= 100
    exposure = round(exposure, 1)
    return exposure


def report(final_report: dict) -> None:
    colors = {True: 'green', False: 'yellow'}

    for contract_name, data in final_report.items():

        click.secho(f'\n\n{contract_name}Agent Exposure {data["exposure"]}%\n'
                    f'===============================================',
                    fg='blue', bold=True)

        for name, call_count in data['counter'].items():
            if name in data['external']:
                visibility = 'E'
            elif name in data['public']:
                visibility = 'P'
            click.secho(f'[{visibility}] {name} ({call_count})', fg=colors[bool(call_count)])


def measure_contract_exposure(agent_class) -> Dict[str, dict]:

    # Twin APIs
    external_functions, public_functions = get_exposed_contract_interfaces(agent_class=agent_class)
    agent_api = collect_agent_api(agent_class=agent_class)
    contract_api = (*external_functions, *public_functions)

    # Analyze
    function_counter = analyze(contract_api=contract_api, agent_api=agent_api)
    exposure = calculate_exposure(data=function_counter)

    # Record
    entry = dict(exposure=exposure,
                 counter=function_counter,
                 public=[f.name for f in public_functions],
                 external=[f.name for f in external_functions])
    result = {agent_class.contract_name: entry}
    return result


def main() -> None:
    results = dict()
    with click.progressbar(AGENTS, label='Analyzing contract exposure') as agents:
        for agent_class in agents:
            result = measure_contract_exposure(agent_class=agent_class)
            results.update(result)
    report(final_report=results)


if __name__ == '__main__':
    click.clear()
    compile()
    main()
