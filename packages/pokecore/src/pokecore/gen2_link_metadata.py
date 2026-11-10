"""Verified English Gold, Silver and Crystal Cable Club boundaries. No reference checkout is needed at runtime.

Banked symbols are (bank, address). WRAM symbols use bank 0 or 1 for the
switchable WRAM bank they live in. Signatures are the first eight bytes at each
code site, checked against the clean retail cartridges.
"""
from .gen1_link_metadata import rom_offset

ADAPTER_ID = "english-gsc-core-cable-v1"
BUILDS = {'d8b8a3600a465308c9953dfa04f0081c05bdcb94': {'version': 'gold',
                                              'symbols': {'WaitForLinkedFriend.loop': (10, 23411),
                                                          'Serial_ExchangeByte': (0, 1851),
                                                          'WaitLinkTransfer': (0, 2094),
                                                          'Gen2ToGen2LinkComms': (10, 16751),
                                                          'LinkTrade': (10, 19065),
                                                          'LinkTrade.save': (10, 19726),
                                                          'SaveAfterLinkTrade': (5, 19199),
                                                          'CloseLink': (10, 23801),
                                                          'hSerialConnectionStatus': (0, 65485),
                                                          'hSerialSend': (0, 65487),
                                                          'hSerialReceive': (0, 65488),
                                                          'hSerialReceivedNewData': (0, 65484),
                                                          'wPlayerLinkAction': (0, 52822),
                                                          'wOtherPlayerLinkAction': (0, 52818),
                                                          'wOtherPlayerLinkMode': (0, 52817),
                                                          'wLinkMode': (1, 53314),
                                                          'wCurTradePartyMon': (0, 52973),
                                                          'ExitLinkCommunications': (10, 18948)},
                                              'signatures': {'WaitForLinkedFriend.loop': 'f0cdfe02283afe01',
                                                             'Serial_ExchangeByte': 'afe0ccf0cdfe0220',
                                                             'WaitLinkTransfer': '3effea52cecd7208',
                                                             'Gen2ToGen2LinkComms': 'cdb443cd2345cdc2',
                                                             'LinkTrade': 'afea57ceea52ce21',
                                                             'LinkTrade.save': '3e0521ff4acf0e28',
                                                             'SaveAfterLinkTrade': 'cdf24b3e05215640',
                                                             'CloseLink': '0e03cd3c03c30b5d',
                                                             'ExitLinkCommunications': 'afeab7d8afe001e0'}},
 '49b163f7e57702bc939d642a18f591de55d92dae': {'version': 'silver',
                                              'symbols': {'WaitForLinkedFriend.loop': (10, 23411),
                                                          'Serial_ExchangeByte': (0, 1851),
                                                          'WaitLinkTransfer': (0, 2094),
                                                          'Gen2ToGen2LinkComms': (10, 16751),
                                                          'LinkTrade': (10, 19065),
                                                          'LinkTrade.save': (10, 19726),
                                                          'SaveAfterLinkTrade': (5, 19199),
                                                          'CloseLink': (10, 23801),
                                                          'hSerialConnectionStatus': (0, 65485),
                                                          'hSerialSend': (0, 65487),
                                                          'hSerialReceive': (0, 65488),
                                                          'hSerialReceivedNewData': (0, 65484),
                                                          'wPlayerLinkAction': (0, 52822),
                                                          'wOtherPlayerLinkAction': (0, 52818),
                                                          'wOtherPlayerLinkMode': (0, 52817),
                                                          'wLinkMode': (1, 53314),
                                                          'wCurTradePartyMon': (0, 52973),
                                                          'ExitLinkCommunications': (10, 18948)},
                                              'signatures': {'WaitForLinkedFriend.loop': 'f0cdfe02283afe01',
                                                             'Serial_ExchangeByte': 'afe0ccf0cdfe0220',
                                                             'WaitLinkTransfer': '3effea52cecd7208',
                                                             'Gen2ToGen2LinkComms': 'cdb443cd2345cdc2',
                                                             'LinkTrade': 'afea57ceea52ce21',
                                                             'LinkTrade.save': '3e0521ff4acf0e28',
                                                             'SaveAfterLinkTrade': 'cdf24b3e05215640',
                                                             'CloseLink': '0e03cd3c03c30b5d',
                                                             'ExitLinkCommunications': 'afeab7d8afe001e0'}},
 'f2f52230b536214ef7c9924f483392993e226cfb': {'version': 'crystal',
                                              'symbols': {'WaitForLinkedFriend.loop': (10, 23865),
                                                          'Serial_ExchangeByte': (0, 1930),
                                                          'WaitLinkTransfer': (0, 2173),
                                                          'Gen2ToGen2LinkComms': (10, 16759),
                                                          'LinkTrade': (10, 19335),
                                                          'LinkTrade.save': (10, 20067),
                                                          'SaveAfterLinkTrade': (5, 19032),
                                                          'CloseLink': (10, 24302),
                                                          'hSerialConnectionStatus': (0, 65483),
                                                          'hSerialSend': (0, 65485),
                                                          'hSerialReceive': (0, 65486),
                                                          'hSerialReceivedNewData': (0, 65482),
                                                          'wPlayerLinkAction': (0, 53078),
                                                          'wOtherPlayerLinkAction': (0, 53074),
                                                          'wOtherPlayerLinkMode': (0, 53073),
                                                          'wLinkMode': (0, 49884),
                                                          'wCurTradePartyMon': (1, 53250),
                                                          'ExitLinkCommunications': (10, 19234)},
                                              'signatures': {'WaitForLinkedFriend.loop': 'f0cbfe02283afe01',
                                                             'Serial_ExchangeByte': 'afe0caf0cbfe0220',
                                                             'WaitLinkTransfer': '3effea52cfcdc108',
                                                             'Gen2ToGen2LinkComms': 'cd2644cd9545cd34',
                                                             'LinkTrade': 'afea57cfea52cf21',
                                                             'LinkTrade.save': '3e0521584acf3e41',
                                                             'SaveAfterLinkTrade': 'cd544b3e05215640',
                                                             'CloseLink': 'afeadcc20e03cd68',
                                                             'ExitLinkCommunications': 'cdb604cddb0f0608'}}}


def build(sha1):
    """The Gen 2 link build for a cartridge SHA-1, or None."""
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
