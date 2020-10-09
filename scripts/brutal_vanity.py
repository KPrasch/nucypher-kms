from eth_account.account import Account
from web3.main import Web3
from web3.providers.rpc import HTTPProvider


def createAddress():
    account = Account.create()
    return account.privateKey, account.address


URI = "https://mainnet.infura.io/v3/c7f107730c14417d84813279b236b582"
provider = HTTPProvider(URI)
w3 = Web3(provider=provider)
print('Connected to provider...')

print('Searching....')
n = 4
while True:
    key, address = createAddress()
    # Start from 2 to ignore 0x
    if n * '0' == address[2:2 + n]:
        eth = w3.eth.getBalance(account=address)
        if eth > 0:
            print(f'address | {eth} ETH')
            print("Found assets! {}".format(address))
            print("Private Key {}".format(key))
            exit()
        print(f'address | 0 ETH')
