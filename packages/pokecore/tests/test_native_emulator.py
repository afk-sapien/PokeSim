"""Optional native conformance checks using the redistributable demo cartridge."""
import io

import pytest

from pokecore.emulator import Emulator, Memory, Registers, demo_rom
from pokecore.emulator_state import checkpoint_metadata, validate_runtime

pytest.importorskip("pyboy_rs")


def test_checkpoint_preserves_pending_inputs_frames_and_outputs():
    with Emulator(demo_rom()) as first, Emulator(demo_rom()) as second:
        first.tick(90)
        first.press("a")
        checkpoint = first.checkpoint()
        second.restore_checkpoint(checkpoint)
        assert second.frame_count == first.frame_count == 90
        assert second.pending_inputs == (("a", True),)
        for count in (1, 2, 12):
            first.tick(count)
            second.tick(count)
            assert first.save() == second.save()
            assert bytes(first.screen.raw_buffer) == bytes(second.screen.raw_buffer)
            assert first.audio_samples() == second.audio_samples()
        assert first.pending_inputs == second.pending_inputs == ()


def test_checkpoint_mismatch_and_invalid_load_do_not_mutate():
    with Emulator(demo_rom()) as machine:
        machine.tick(90)
        before = machine.checkpoint()
        detached = machine.checkpoint()
        detached["settings"]["color_palette"][0] = 0
        with pytest.raises(ValueError, match="settings mismatch"):
            machine.restore_checkpoint(detached)
        assert machine.checkpoint() == before
        for changed in ({"rom_sha256": "wrong"}, {"settings": {}}, {"state": b"invalid"},
                        {"pending_inputs": [("bogus", True)]}, {"frames": -1}):
            with pytest.raises(ValueError):
                machine.restore_checkpoint({**before, **changed})
            assert machine.checkpoint() == before


def test_views_are_owned_by_core_and_output_is_readonly():
    with Emulator(demo_rom()) as machine:
        assert isinstance(machine.memory, Memory)
        assert isinstance(machine.register_file, Registers)
        assert machine.screen.raw_buffer.readonly
        assert machine.sound.raw_buffer.readonly
        machine.memory[0xc120:0xc123] = [10, 20, 30]
        saved = machine.memory[0xc120:0xc123]
        machine.memory[0xc120] = 40
        assert saved == [10, 20, 30]
        memory = machine.memory
    with pytest.raises(RuntimeError, match="closed"):
        memory[0xc120]


def test_hook_context_register_edits_and_cleanup():
    with Emulator(demo_rom()) as machine:
        events = []
        original = machine.memory[0, 0x100]
        def reached(context):
            events.append(context)
            machine.register_file.PC = 0x101
            machine.register_file.A = 0x45
        machine.hook_register(0, 0x100, reached, "entry")
        machine.tick(90)
        assert events == ["entry"]
        machine.hook_deregister(0, 0x100)
        assert machine.memory[0, 0x100] == original


def test_explicit_cartridge_export_and_isolated_import():
    rom = bytearray(32768)
    rom[0x147:0x14a] = bytes((3, 0, 2))
    for value in rom[0x134:0x14d]:
        rom[0x14d] = (rom[0x14d] - value - 1) & 255
    output = io.BytesIO()
    with Emulator(io.BytesIO(rom)) as first:
        first.memory[0, 0xa000] = 77
        first.stop(ram_file=output)
    assert len(output.getvalue()) == 8192
    output.seek(0)
    with Emulator(io.BytesIO(rom), ram_file=output) as loaded, Emulator(io.BytesIO(rom)) as fresh:
        assert loaded.memory[0, 0xa000] == 77
        assert fresh.memory[0, 0xa000] != 77


def test_legacy_import_is_distinct_from_exact_resume():
    validate_runtime({"pyboy_version": "2.7.0"})
    with pytest.raises(ValueError):
        validate_runtime({"pyboy_version": "2.7.0"}, exact=True)
    manifest = checkpoint_metadata()
    validate_runtime(manifest, exact=True)
    manifest["emulator"]["native_sha256"] = "different"
    with pytest.raises(ValueError, match="original emulator"):
        validate_runtime(manifest, exact=True)
    assert checkpoint_metadata()["emulator"]["native_sha256"] != "different"


def test_migrated_outputs_record_actual_runtime_and_source_lineage():
    from pokecore.emulator_state import retag_checkpoint, same_runtime_or_recorded_migration
    source = {"pyboy_version": "2.7.0", "frame": 100}
    output = retag_checkpoint(source)
    assert output["pyboy_version"] == "2.7.0"
    assert output["emulator"]["backend"] == "pyboy-rs"
    assert output["frame"] == source["frame"]
    assert source == {"pyboy_version": "2.7.0", "frame": 100}
    assert same_runtime_or_recorded_migration(source, output)
    output["emulator_migration"]["from"] = {"backend": "unknown"}
    assert not same_runtime_or_recorded_migration(source, output)
