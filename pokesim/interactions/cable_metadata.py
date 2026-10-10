"""Shared verified Gen1 link metadata."""
from pokesim_core.gen1_link_metadata import ADAPTER_ID as ADAPTER_ID, BUILDS as CORE_BUILDS, SOURCE_REVISION as SOURCE_REVISION

from ..yellow import YELLOW_SHA1

_RED = CORE_BUILDS['ea9bcae617fdf159b045185467ae58b2e4a48b9a']

# Yellow runs the Red and Blue link code from other ROM addresses, taken from
# pret/pokeyellow symbols. A Yellow emulator reads memory through Red addresses,
# so its RAM symbols stay the Red ones.
YELLOW_CODE = {
    'CableClubNPC.establishConnectionLoop': ((1, 0x7060), 'f0aafe022829fe01'),
    'Serial_ExchangeByte': ((0, 0x1FF6), 'afe0a9f0aafe0220'),
    'Serial_SyncAndExchangeNybble': ((0, 0x20DB), '3effea3ecccd1f21'),
    'CableClub_DoBattleOrTrade': ((1, 0x53A5), '0e50cd2f37cddd16'),
    'TradeCenter_SelectMon': ((1, 0x55CA), 'cddd16cddb3d0609'),
    'TradeCenter_Trade': ((1, 0x58EF), '0e64cd2f37afea43'),
    'TradeCenter_Trade.tradeCompleted': ((1, 0x5A8B), '21b86d060ecd843e'),
    'SavePartyAndDexData': ((28, 0x7B56), 'cd9f7e3e01ea0040'),
    'ReturnToCableClubRoom': ((1, 0x581E), 'cdd83d21c3cf7ef5'),
}

BUILDS = dict(CORE_BUILDS)
BUILDS[YELLOW_SHA1] = {
    'version': 'Yellow',
    'symbols': {**_RED['symbols'], **{name: site for name, (site, _) in YELLOW_CODE.items()}},
    'signatures': {name: signature for name, (_, signature) in YELLOW_CODE.items()},
}
