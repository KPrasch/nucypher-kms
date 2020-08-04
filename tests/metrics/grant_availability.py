#!/usr/bin/env python3

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

import datetime
import os
import shutil
import sys
from typing import Set, Optional, Tuple

import maya
from umbral.keys import UmbralPrivateKey

from nucypher.characters.lawful import Bob, Ursula
from nucypher.config.characters import AliceConfiguration
from nucypher.utilities.logging import GlobalLoggerSettings


INSECURE_PASSWORD = "TEST_ALICIA_INSECURE_DEVELOPMENT_PASSWORD"
TEMP_ALICE_DIR = os.path.join('/', 'tmp', 'grant-test')


def main(handpicked_ursulas: Set[Ursula], domain: str, iterations: Optional[int] = 1) -> Tuple[int, int]:

    # Alice
    alice_config = AliceConfiguration(
        config_root=os.path.join(TEMP_ALICE_DIR),
        domains={domain},
        known_nodes=handpicked_ursulas,
        start_learning_now=False,
        federated_only=True,
        learn_on_same_thread=True,
    )

    alice_config.initialize(password=INSECURE_PASSWORD)
    alice_config.keyring.unlock(password=INSECURE_PASSWORD)
    alicia = alice_config.produce()
    alicia.start_learning_loop(now=True)

    # Policy
    label = f"random-label-{os.urandom(4).hex()}".encode()
    policy_pubkey = alicia.get_policy_encrypting_key_from_label(label)
    print("Policy Encrypting Key ({}) | {}".format(label.decode("utf-8"), policy_pubkey.to_bytes().hex()))


    # Bob
    bob_verifying_key = UmbralPrivateKey.gen_key().to_bytes()
    decrypting_key = UmbralPrivateKey.gen_key().to_bytes()
    doctor_strange = Bob.from_public_keys(verifying_key=bob_verifying_key, encrypting_key=decrypting_key, federated_only=True)

    # Grant
    policy_end_datetime = maya.now() + datetime.timedelta(days=5)
    m, n = len(handpicked_ursulas), len(handpicked_ursulas)

    success, fail = 0, 0
    for attempt in range(iterations):
        try:
            policy = alicia.grant(m=m, n=n,
                                  handpicked_ursulas=handpicked_ursulas,
                                  expiration=policy_end_datetime,
                                  bob=doctor_strange,
                                  label=label)
        except Exception:  # TODO: What to catch here?
            fail += 1
        else:
            success += 1

    return success, fail



if __name__ == '__main__':
    try:
        SEEDNODE_URI = sys.argv[1]
    except IndexError:
        raise RuntimeError('Pass a test ursula URI as an argument')

    shutil.rmtree(TEMP_ALICE_DIR, ignore_errors=True)
    GlobalLoggerSettings.start_console_logging()

    ursulas = {
        Ursula.from_seed_and_stake_info(seed_uri=SEEDNODE_URI, federated_only=False),
    }

    main(domain='ibex', handpicked_ursulas=ursulas)
    print("Done!")
