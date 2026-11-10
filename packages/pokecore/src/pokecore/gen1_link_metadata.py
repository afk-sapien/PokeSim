"""Verified English retail adapter metadata. No reference checkout is needed at runtime."""
from .rom import rom_offset

ADAPTER_ID = "english-rb-core-cable-v1"
SOURCE_REVISION = "705ec4ddc2f0e5a1265170b33f101141c5892960"
BUILDS = {
    'ea9bcae617fdf159b045185467ae58b2e4a48b9a': {
        "version": 'Red',
        "symbols": {
            'wPartyCount': (0, 53603),
            'wPartyMons': (0, 53611),
            'wPartyMonNicks': (0, 53941),
            'wPartyMonOT': (0, 53875),
            'wBoxDataStart': (0, 55936),
            'wBoxDataEnd': (0, 57058),
            'wLinkState': (0, 53547),
            'wCurrentMenuItem': (0, 52262),
            'wWhichTradeMonSelectionMenu': (0, 52297),
            'wSerialExchangeNybbleSendData': (0, 52290),
            'wSerialSyncAndExchangeNybbleReceiveData': (0, 52285),
            'wSerialExchangeNybbleReceiveData': (0, 52286),
            'hSerialConnectionStatus': (0, 65450),
            'hSerialSendData': (0, 65452),
            'hSerialReceiveData': (0, 65453),
            'hSerialReceivedNewData': (0, 65449),
            'CableClubNPC.establishConnectionLoop': (1, 29163),
            'Serial_ExchangeByte': (0, 8602),
            'Serial_SyncAndExchangeNybble': (0, 8831),
            'CableClub_DoBattleOrTrade': (1, 21271),
            'TradeCenter_SelectMon': (1, 21808),
            'TradeCenter_Trade': (1, 22601),
            'TradeCenter_Trade.tradeCompleted': (1, 23006),
            'SavePartyAndDexData': (28, 30735),
            'ReturnToCableClubRoom': (1, 22397),
            'sBox1': (2, 40960),
            'sBox2': (2, 42082),
            'sBox3': (2, 43204),
            'sBox4': (2, 44326),
            'sBox5': (2, 45448),
            'sBox6': (2, 46570),
            'sBox7': (3, 40960),
            'sBox8': (3, 42082),
            'sBox9': (3, 43204),
            'sBox10': (3, 44326),
            'sBox11': (3, 45448),
            'sBox12': (3, 46570),
        },
        "signatures": {
            'CableClubNPC.establishConnectionLoop': 'f0aafe022829fe01',
            'Serial_ExchangeByte': 'afe0a9f0aafe0220',
            'Serial_SyncAndExchangeNybble': '3effea3ecccdc322',
            'CableClub_DoBattleOrTrade': '0e50cd3937cd0f19',
            'TradeCenter_SelectMon': 'cd0f19cde65acdf2',
            'TradeCenter_Trade': '0e64cd3937afea43',
            'TradeCenter_Trade.tradeCompleted': '210e6d060ecdd635',
            'SavePartyAndDexData': '3e0aea00003e01ea',
            'ReturnToCableClubRoom': 'cdd43d21c4cf7ef5',
        },
    },
    'd7037c83e1ae5b39bde3c30787637ba1d4c48ce2': {
        "version": 'Blue',
        "symbols": {
            'wPartyCount': (0, 53603),
            'wPartyMons': (0, 53611),
            'wPartyMonNicks': (0, 53941),
            'wPartyMonOT': (0, 53875),
            'wBoxDataStart': (0, 55936),
            'wBoxDataEnd': (0, 57058),
            'wLinkState': (0, 53547),
            'wCurrentMenuItem': (0, 52262),
            'wWhichTradeMonSelectionMenu': (0, 52297),
            'wSerialExchangeNybbleSendData': (0, 52290),
            'wSerialSyncAndExchangeNybbleReceiveData': (0, 52285),
            'wSerialExchangeNybbleReceiveData': (0, 52286),
            'hSerialConnectionStatus': (0, 65450),
            'hSerialSendData': (0, 65452),
            'hSerialReceiveData': (0, 65453),
            'hSerialReceivedNewData': (0, 65449),
            'CableClubNPC.establishConnectionLoop': (1, 29163),
            'Serial_ExchangeByte': (0, 8602),
            'Serial_SyncAndExchangeNybble': (0, 8831),
            'CableClub_DoBattleOrTrade': (1, 21271),
            'TradeCenter_SelectMon': (1, 21808),
            'TradeCenter_Trade': (1, 22601),
            'TradeCenter_Trade.tradeCompleted': (1, 23006),
            'SavePartyAndDexData': (28, 30735),
            'ReturnToCableClubRoom': (1, 22397),
            'sBox1': (2, 40960),
            'sBox2': (2, 42082),
            'sBox3': (2, 43204),
            'sBox4': (2, 44326),
            'sBox5': (2, 45448),
            'sBox6': (2, 46570),
            'sBox7': (3, 40960),
            'sBox8': (3, 42082),
            'sBox9': (3, 43204),
            'sBox10': (3, 44326),
            'sBox11': (3, 45448),
            'sBox12': (3, 46570),
        },
        "signatures": {
            'CableClubNPC.establishConnectionLoop': 'f0aafe022829fe01',
            'Serial_ExchangeByte': 'afe0a9f0aafe0220',
            'Serial_SyncAndExchangeNybble': '3effea3ecccdc322',
            'CableClub_DoBattleOrTrade': '0e50cd3937cd0f19',
            'TradeCenter_SelectMon': 'cd0f19cde65acdf2',
            'TradeCenter_Trade': '0e64cd3937afea43',
            'TradeCenter_Trade.tradeCompleted': '210e6d060ecdd635',
            'SavePartyAndDexData': '3e0aea00003e01ea',
            'ReturnToCableClubRoom': 'cdd43d21c4cf7ef5',
        },
    },
}

# Yellow runs the Red and Blue link code from other ROM addresses, taken from
# pret/pokeyellow symbols. Read Yellow RAM through ``yellow.RedLayoutMemory`` (or
# ``yellow.YellowEmulator``), so its RAM and SRAM symbols stay the Red ones.
YELLOW_SOURCE_REVISION = "e89ead154b9968aa50eed9328ff2b38b6c194382"
YELLOW_SHA1 = 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'
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
_RED = BUILDS['ea9bcae617fdf159b045185467ae58b2e4a48b9a']
BUILDS[YELLOW_SHA1] = {
    "version": 'Yellow',
    "symbols": {**_RED["symbols"], **{name: site for name, (site, _) in YELLOW_CODE.items()}},
    "signatures": {name: signature for name, (_, signature) in YELLOW_CODE.items()},
}


def build(sha1):
    """The link build for a cartridge SHA-1, or None for a cartridge without Gen 1 link metadata."""
    return BUILDS.get(sha1)


def verify_signatures(rom, sha1):
    """Names of code sites whose first bytes in ``rom`` differ from the recorded signature."""
    metadata = BUILDS[sha1]
    rom = bytes(rom)
    failed = []
    for name, signature in metadata["signatures"].items():
        offset = rom_offset(*metadata["symbols"][name])
        expected = bytes.fromhex(signature)
        if rom[offset:offset + len(expected)] != expected:
            failed.append(name)
    return failed
