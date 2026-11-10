import pytest

from pokecore.emulator import Emulator, demo_rom


@pytest.mark.parametrize('render,sound', [(False, False), (True, False), (True, True)])
def test_combined_read_matches_separate_ticks_with_hooks_and_inputs(render, sound):
    pytest.importorskip('pyboy_rs')
    with Emulator(demo_rom()) as separate, Emulator(demo_rom()) as combined:
        calls = [[], []]
        for i, emulator in enumerate((separate, combined)):
            def callback(context, emulator=emulator, i=i):
                calls[i].append(context)
                emulator.memory[0xc000] = 37
                emulator.register_file.PC = 0x101
                emulator.press('a')
            emulator.hook_register(0, 0x100, callback, 'entry')
        for count in (90, 1, 4, 8):
            separate.tick(count, render=render, sound=sound)
            raw = combined.tick_read(count, 0xc000, 0xe000, render=render, sound=sound)
            assert raw == separate.memory.read_bytes(0xc000, 0xe000)
            assert combined.save() == separate.save()
        assert calls == [['entry'], ['entry']]
        original = combined.save()
        with pytest.raises(ValueError):
            combined.tick_read(2, 4, 3)
        assert combined.save() == original
        assert combined.tick_read(1, 65536, 65536) == b''
    with pytest.raises(RuntimeError):
        combined.tick_read(1, 0, 1)
