
WINDING_DOWN_NOTICE = f"""

Over time, as the locked stake duration decreases
i.e. `winds down`, you will receive decreasing inflationary rewards.

Instead, by disabling `wind down` (default) the locked stake duration
can remain constant until you specify that `wind down` should begin. By
keeping the locked stake duration constant, it ensures that you will
receive maximum inflation compensation.

If `wind down` was previously disabled, you can enable it at any point
and the locked duration will decrease after each period.

For more information see https://docs.nucypher.com/en/latest/architecture/sub_stakes.html#winding-down.
"""

RESTAKE_LOCK_NOTICE = f"""
By enabling the re-staking lock for {staking_address}, you are committing to automatically
re-stake all rewards until a future period.  You will not be able to disable re-staking until {release_period}.
"""

CHARACTER_DESTRUCTION = '''
Delete all {name} character files including:
    - Private and Public Keys ({keystore})
    - Known Nodes             ({nodestore})
    - Node Configuration File ({config})
    - Database                ({database})

Are you sure?'''

SUCCESSFUL_DESTRUCTION = "Successfully destroyed NuCypher configuration"


#
# URSULA_OPERATOR_NOTICE = f"""
# * Ursula Node Operator Notice *
# -------------------------------
#
# By agreeing to stake {str(value)} ({str(value.to_nunits())} NuNits):
#
# - Staked tokens will be locked for the stake duration.
#
# - You are obligated to maintain a networked and available Ursula-Worker node
#   bonded to the staker address {staker_address} for the duration
#   of the stake(s) ({lock_periods} periods).
#
# - Agree to allow NuCypher network users to carry out uninterrupted re-encryption
#   work orders at-will without interference.
#
# Failure to keep your node online, or violation of re-encryption work orders
# will result in the loss of staked tokens as described in the NuCypher slashing protocol.
#
# Keeping your Ursula node online during the staking period and successfully
# producing correct re-encryption work orders will result in rewards
# paid out in ethers retro-actively and on-demand.
#
# Accept ursula node operator obligation?"""
#
# """


