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
from constant_sorrow.constants import FALLBACK

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


def scrape_ast_requirements(ast_functions) -> Dict:
    function_requirements = dict()
    for node in ast_functions:
        filters = {'nodeType': "FunctionCall", "expression.name": "require"}
        requires = node.children(include_children=False, filters=filters)
        function_requirements[node.name] = requires
    return function_requirements


def scrape_ast_functions(contract_data, visibility: str, include_children: bool = False, requirements: bool = False):
    ast = contract_data['ast']
    nodes = solcast.from_ast(ast)
    filters = {'nodeType': "FunctionDefinition", "visibility": visibility}
    ast_functions = nodes.children(include_children=include_children, filters=filters)
    function_requirements = dict()
    if requirements:
        function_requirements = scrape_ast_requirements(ast_functions=ast_functions)
    named_nodes = {n.name: dict(function=n, requirements=function_requirements.get(n.name)) for n in ast_functions}
    return named_nodes


def get_exposed_contract_interfaces(agent_class: Type[Agent], version: str = 'latest', requirements: bool = False):
    contract_data = compile_contract(agent_class=agent_class, version=version)
    external_functions = scrape_ast_functions(contract_data=contract_data, visibility='external', requirements=requirements)
    public_functions = scrape_ast_functions(contract_data=contract_data, visibility='public', requirements=requirements)
    return external_functions, public_functions


def get_callable_cell_contents(agent_method: Callable) -> List[Callable]:
    if isinstance(agent_method, property):
        agent_method = agent_method.fget  # Handle properties
    members = inspect.getmembers(agent_method, inspect.isfunction)
    callable_cells = list()
    for member in members:
        callable_cells.extend([c for c in member if callable(c)])
    return callable_cells


def setup_function_counter(contract_api) -> Counter:
    function_counter = Counter()
    for name, contract_function in contract_api.items():
        function_counter[name] = 0
    return function_counter


def analyze_exposure(contract_api, agent_api) -> Counter:

    def sample(funcs: Iterable[Callable], function_counter: Counter) -> None:
        for func in funcs:
            internal_calls = inspect.getclosurevars(func)
            contract_calls = tuple(f for f in internal_calls.unbound if f in function_counter)
            for call in contract_calls:
                function_counter[call] += 1

    function_counter = setup_function_counter(contract_api=contract_api)
    for agent_method in agent_api:
        callable_code_cells = get_callable_cell_contents(agent_method=agent_method)
        sample(funcs=callable_code_cells, function_counter=function_counter)

    # Handle fallback (payable) functions
    fallback_function_detected = '' in function_counter
    if fallback_function_detected:
        function_counter[FALLBACK] = function_counter.pop('')

    return function_counter


def calculate_exposure(data: Counter) -> float:
    try:
        exposure = sum(1 for v in data.values() if v > 0) / len(data)
    except ZeroDivisionError:
        exposure = 0
    exposure *= 100
    exposure = round(exposure, 1)
    return exposure


def paint_row(api: Dict, counter: Counter, visibility: str):
    colors = {True: 'green', False: 'yellow', FALLBACK: 'cyan'}  # TODO: Make constant
    for name, function in api.items():
        if name == '':
            name, color = FALLBACK, colors[FALLBACK]
            call_count = counter[name]
        else:
            call_count = counter[name]
            color = colors[bool(call_count)]

        row = f'[{visibility}] {name} ({call_count})'
        click.secho(row, fg=color)


def report(final_report: dict) -> None:
    for contract_name, contract_report in final_report.items():
        exposure = contract_report['exposure']
        external = contract_report['external']
        public = contract_report['public']
        counter = contract_report['counter']

        click.secho(f'\n\n{contract_name}Agent Exposure {exposure}%\n'
                    f'===============================================',
                    fg='blue', bold=True)

        paint_row(api=external, counter=counter, visibility='E')
        paint_row(api=public, counter=counter, visibility='P')

        # for name, call_count in counter.items():
        #     click.secho(f'[{visibility}] {name} ({call_count})', fg=colors[bool(call_count)])


def measure_contract_exposure(agent_class, requirements: bool = False) -> Dict[str, dict]:

    # Twin APIs
    external_functions, public_functions = get_exposed_contract_interfaces(agent_class=agent_class, requirements=requirements)
    agent_api = collect_agent_api(agent_class=agent_class)

    # Analyze
    external_counter = analyze_exposure(contract_api=external_functions, agent_api=agent_api)
    public_counter = analyze_exposure(contract_api=public_functions, agent_api=agent_api)
    function_counter = Counter({**external_counter, **public_counter})
    exposure = calculate_exposure(data=function_counter)

    # Record
    entry = dict(exposure=exposure,
                 counter=function_counter,
                 public=public_functions,
                 external=external_functions)
    result = {agent_class.contract_name: entry}
    return result


def measure_project_exposure():
    results = dict()
    with click.progressbar(AGENTS, label='Analyzing contract exposure') as agents:
        for agent_class in agents:
            result = measure_contract_exposure(agent_class=agent_class, requirements=True)
            results.update(result)
    report(final_report=results)


def main() -> None:
    measure_project_exposure()


if __name__ == '__main__':
    click.clear()
    compile()
    main()
