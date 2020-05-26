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
from collections import Counter, defaultdict

import click
import inspect
import solcast
from constant_sorrow.constants import FALLBACK, EXCLUDE
from functools import partial
from typing import Type, Dict, Callable, Iterable, List, Tuple

from nucypher.blockchain.eth.agents import (
    NucypherTokenAgent,
    StakingEscrowAgent,
    PolicyManagerAgent,
    WorkLockAgent
)
from nucypher.blockchain.eth.sol.compile import SolidityCompiler
from nucypher.types import Agent
from tests.utils.solidity import collect_agent_api

COLORS = {
    True: 'green',
    False: 'yellow',
    'receiveApproval':  'bright_black',
    FALLBACK: 'bright_black',
    EXCLUDE: 'bright_black'
}

DEFAULT_EXCLUDE = (FALLBACK, 'receiveApproval')


def compile() -> Dict:
    compiler = SolidityCompiler()
    compiler_output: Dict[str, Dict] = compiler.compile()
    return compiler_output


def get_compiled_contract(compiler_output, agent_class, version: str) -> Dict[str, Dict]:
    compiled_contract_versions = compiler_output[agent_class.contract_name]
    if version == 'latest':
        contract_versions = list(compiled_contract_versions.items())
        version_number, contract_data = contract_versions[-1]  # TODO: Better way to get last version
    else:
        version_number, contract_data = compiled_contract_versions[version]
    return contract_data


def source_reader(source, offset: Tuple):
    """coroutine for peeking at solidity source"""
    start, stop = offset
    source.seek(start)
    snippet = source.read(stop-start)
    return snippet


def scrape_ast_requirements(ast_functions, seeker: Callable) -> Dict[str, str]:
    function_requirements = dict()
    for node in ast_functions:
        filters = {'nodeType': "FunctionCall", "expression.name": "require"}
        require_nodes = node.children(include_children=False, filters=filters)
        if require_nodes:
            require_snippets = list()
            for require in require_nodes:
                snippet = seeker(offset=require.offset)
                require_snippets.append((require.offset, snippet))
            function_requirements[node.name] = require_snippets
    return function_requirements


def scrape_ast_functions(contract_data, visibility: str, include_children: bool = False, requirements: bool = False):
    ast = contract_data['ast']
    source_path = ast['absolutePath']
    nodes = solcast.from_ast(ast)
    filters = {'nodeType': "FunctionDefinition", "visibility": visibility}
    ast_functions = nodes.children(include_children=include_children, filters=filters)
    function_requirements = dict()
    if requirements:
        seeker = partial(source_reader, source=open(source_path, 'r'))  # They call me the seeker
        function_requirements = scrape_ast_requirements(ast_functions=ast_functions, seeker=seeker)
    named_nodes = {n.name: dict(function=n, requirements=function_requirements.get(n.name)) for n in ast_functions}
    return named_nodes


def get_exposed_contract_interfaces(compiler_output,
                                    agent_class: Type[Agent],
                                    version: str = 'latest',
                                    requirements: bool = False):

    contract_data = get_compiled_contract(agent_class=agent_class, version=version, compiler_output=compiler_output)
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


def setup_function_counter(contract_api: Tuple[str]) -> Counter:
    function_counter = Counter()
    for name in contract_api:
        function_counter[name] = 0
    return function_counter


def sample(funcs: Iterable[Callable], function_counter: Counter, codex: Dict) -> None:
    for func in funcs:
        internal_calls = inspect.getclosurevars(func)
        contract_calls = tuple(f for f in internal_calls.unbound if f in function_counter)
        for call in contract_calls:
            function_counter[call] += 1
            codex[call].append(func.__name__)


def analyze_exposure(agent_api: List[Callable],
                     codex: Dict[str, str],
                     counter: Counter,
                     ) -> None:

    for agent_method in agent_api:
        callable_code_cells = get_callable_cell_contents(agent_method=agent_method)
        sample(funcs=callable_code_cells, function_counter=counter, codex=codex)

    # Special cases...
    # Handle fallback (payable) functions
    fallback_function_detected = '' in counter
    if fallback_function_detected:
        counter[FALLBACK] = counter.pop('')


def calculate_exposure(data: Counter, exclude: Tuple[str] = DEFAULT_EXCLUDE) -> float:
    for item in DEFAULT_EXCLUDE:
        if item not in exclude:
            exclude = (item, *exclude)
    try:
        exposure = sum(1 for k, v in data.items() if v > 0
                       or k in exclude) / len(data)
    except ZeroDivisionError:
        exposure = 0
    exposure *= 100
    exposure = round(exposure, 1)
    return exposure


def paint_requirements(requirements, max_width: int = 25):
    for location, req in requirements:
        pretty_req = req.strip().replace('require', '').split()
        pretty_req = ' '.join(pretty_req)
        pretty_req = (pretty_req[:max_width] + '...') if len(pretty_req) > max_width else pretty_req
        req_row = f'    - require @ {location} {pretty_req}'
        click.secho(req_row, fg='blue')


def resolve_row_details(name, exclude, counter):
    if name in ('', FALLBACK):
        name, call_count, color = FALLBACK, counter[name], COLORS[FALLBACK]
    elif name in exclude:
        call_count, color = counter[name], COLORS[EXCLUDE]
    elif name in COLORS:
        call_count, color = counter[name], COLORS[name]
    else:
        call_count = counter[name]
        color = COLORS[bool(call_count)]
    return name, call_count, color


def paint_row(api: Dict,
              counter: Counter,
              visibility: str,
              details: Dict,
              show_requirements: bool = True,
              exclude: Tuple = tuple()
              ) -> None:
    for name, function in api.items():
        name, call_count, color = resolve_row_details(name=name, counter=counter, exclude=exclude)
        reqs = function.get('requirements')
        if show_requirements and reqs:
            paint_requirements(requirements=reqs)
        line_location = function['function'].offset[0]
        agent_detail = ', '.join(details.get(name, ''))
        row = f'[{visibility}] {name} @ {line_location} ({call_count}) | {agent_detail}'
        click.secho(row, fg=color)


def report(final_report: Dict) -> None:
    for contract_name, contract_report in final_report.items():
        excluded = contract_report['excluded']
        exposure = contract_report['exposure']
        external = contract_report['external']
        public = contract_report['public']
        counter = contract_report['counter']
        codex = contract_report['codex']
        click.secho(f'\n\n{contract_name}Agent Exposure {exposure}% ({len(counter)})\n'
                    f'===============================================', fg='blue', bold=True)
        paint_row(api=external, counter=counter, visibility='E', exclude=excluded, details=codex)
        paint_row(api=public, counter=counter, visibility='P', exclude=excluded, details=codex)


def measure_contract_exposure(compiler_output: Dict[str, dict],
                              agent_class: Type[Agent],
                              requirements: bool = True
                              ) -> Dict[str, dict]:

    # Twin APIs
    external, public = get_exposed_contract_interfaces(compiler_output=compiler_output,
                                                       agent_class=agent_class,
                                                       requirements=requirements)
    agent_api = collect_agent_api(agent_class=agent_class)

    # Analyze
    codex = defaultdict(list)
    contract_api = (*external, *public)
    function_counter: Counter = setup_function_counter(contract_api=contract_api)
    analyze_exposure(agent_api=agent_api, codex=codex, counter=function_counter)
    exposure = calculate_exposure(data=function_counter, exclude=agent_class._excluded_interfaces)

    # Record
    report = dict(exposure=exposure,
                  counter=function_counter,
                  codex=codex,
                  public=public,
                  excluded=agent_class._excluded_interfaces,
                  external=external)

    return report


def measure_project_exposure(compiler_output: Dict, capture_requirements: bool = True):

    AGENTS = (

        # TODO: Source contract names another way while preserving relation to agents
        NucypherTokenAgent,
        StakingEscrowAgent,
        PolicyManagerAgent,
        WorkLockAgent,

        # TODO: AST path not resolving absolutely
        # AdjudicatorAgent,
        # MultiSigAgent,
        # PreallocationEscrowAgent,

    )

    results = dict()
    with click.progressbar(AGENTS, label='Analyzing contract exposure') as agents:
        for agent_class in agents:
            single_report = measure_contract_exposure(compiler_output=compiler_output,
                                                      agent_class=agent_class,
                                                      requirements=capture_requirements)
            entry = {agent_class.contract_name: single_report}
            results.update(entry)
    report(final_report=results)


if __name__ == '__main__':
    click.clear()
    compiler_output = compile()
    measure_project_exposure(compiler_output)
