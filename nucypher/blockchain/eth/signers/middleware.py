from cytoolz.functoolz import compose
from typing import Any, Callable, List
from web3._utils.transactions import fill_nonce
from web3._utils.transactions import fill_transaction_defaults
from web3.main import Web3
from web3.middleware.signing import format_transaction
from web3.types import Middleware, RPCEndpoint, RPCResponse


def construct_signer_middleware(signer) -> Middleware:

    accounts: List[str] = signer.accounts

    def sign_and_send_raw_middleware(make_request: Callable[[RPCEndpoint, Any], Any],
                                     w3: Web3) -> Callable[[RPCEndpoint, Any], RPCResponse]:

        format_and_fill_tx = compose(
            format_transaction,
            fill_transaction_defaults(w3),
            fill_nonce(w3)
        )

        def middleware(method: RPCEndpoint, params: Any) -> RPCResponse:

            # Enforced only for one endpoint
            if method != "eth_sendTransaction":
                return make_request(method, params)

            # Fill nonce
            transaction = format_and_fill_tx(params[0])

            # Disqualifications
            if 'from' not in transaction:
                return make_request(method, params)
            elif transaction.get('from') not in accounts:
                return make_request(method, params)

            # Sign & Send Raw
            raw_tx = signer.sign_transaction(transaction)
            result = make_request(RPCEndpoint("eth_sendRawTransaction"), [raw_tx])
            return result

        return middleware

    return sign_and_send_raw_middleware
