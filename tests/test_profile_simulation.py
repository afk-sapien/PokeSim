from pokesim.audio import AudioFeed
from pokesim.emulator import Emulator
from pokesim.replay.profile_simulation import listen


def test_audio_mode_reads_the_feed_as_the_page_does():
    emu = Emulator.__new__(Emulator)
    emu.speed, emu.paused, emu.manual_mode = 1, False, False
    emu.audio = AudioFeed()
    sequence = listen(emu, -1)
    assert sequence == 0
    assert emu.audio.active()
    emu.audio.publish(b'ab')
    assert listen(emu, sequence) == 1
