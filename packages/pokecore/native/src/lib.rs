use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyFrozenSet, PyList, PyTuple};

fn text(raw: &[u8]) -> String {
    let mut out = String::new();
    for &c in raw {
        match c {
            0 | 0x50 => break,
            0x80..=0x99 => out.push((b'A' + (c - 0x80)) as char),
            0xa0..=0xb9 => out.push((b'a' + (c - 0xa0)) as char),
            0xf6..=0xff => out.push((b'0' + (c - 0xf6)) as char),
            0x7f => out.push(' '),
            0xba => out.push('é'),
            0xe0 => out.push('\''),
            0xe1 => out.push_str("PK"),
            0xe2 => out.push_str("MN"),
            0xe3 => out.push('-'),
            0xe6 => out.push('?'),
            0xe7 => out.push('!'),
            0xe8 | 0xf2 => out.push('.'),
            0xef => out.push('♂'),
            0xf0 => out.push('$'),
            0xf1 => out.push('×'),
            0xf4 => out.push(','),
            0xf5 => out.push('♀'),
            0x60..=0xff => out.push('?'),
            _ => (),
        }
    }
    out.trim().to_owned()
}

fn bcd(raw: &[u8]) -> u32 {
    raw.iter().fold(0, |n, c| {
        n * 100 + u32::from(c >> 4) * 10 + u32::from(c & 15)
    })
}

fn word(raw: &[u8], offset: usize) -> u16 {
    u16::from_be_bytes([raw[offset], raw[offset + 1]])
}

fn party<'py>(
    py: Python<'py>,
    raw: &[u8],
    max_pp: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyList>> {
    let count = usize::from(raw[0x1163].min(6));
    if max_pp.len() != count * 4 {
        return Err(PyValueError::new_err(
            "Expected four maximum PP values per party slot",
        ));
    }
    let out = PyList::empty(py);
    for index in 0..count {
        let base = 0x116b + index * 44;
        let block = &raw[base..base + 44];
        let row = PyDict::new(py);
        for (name, value) in [
            ("species", block[0]),
            ("level", block[33]),
            ("status", block[4]),
        ] {
            row.set_item(name, value)?;
        }
        for (name, offset) in [
            ("hp", 1),
            ("max_hp", 34),
            ("attack", 36),
            ("defense", 38),
            ("speed", 40),
            ("special", 42),
            ("trainer_id", 12),
        ] {
            row.set_item(name, word(block, offset))?;
        }
        row.set_item(
            "experience",
            (u32::from(block[14]) << 16) | (u32::from(block[15]) << 8) | u32::from(block[16]),
        )?;
        row.set_item("types", (block[5], block[6]))?;
        row.set_item("moves", PyTuple::new(py, &block[8..12])?)?;
        row.set_item(
            "pp",
            PyTuple::new(py, block[29..33].iter().map(|v| v & 63))?,
        )?;
        row.set_item("max_pp", max_pp.get_slice(index * 4, index * 4 + 4))?;
        let (a, d, s, c) = (
            block[27] >> 4,
            block[27] & 15,
            block[28] >> 4,
            block[28] & 15,
        );
        let hp = ((a & 1) << 3) | ((d & 1) << 2) | ((s & 1) << 1) | (c & 1);
        row.set_item("dvs", (hp, a, d, s, c))?;
        row.set_item(
            "stat_exp",
            PyTuple::new(py, (17..27).step_by(2).map(|i| word(block, i)))?,
        )?;
        let nick = 0x12b5 + index * 11;
        row.set_item("nick", text(&raw[nick..nick + 11]))?;
        out.append(row)?;
    }
    Ok(out)
}

/// Mirrors `wild_shiny` in snapshot.py: original DVs survive Transform; captures are exempt.
fn wild_shiny(raw: &[u8]) -> bool {
    if raw[0x1057] != 1 || raw[0x111c] != 0 || raw[0xf0b] == 2 {
        return false;
    }
    let at = if raw[0x1069] & 8 != 0 { 0xceb } else { 0xff1 };
    raw[at] & 0x2f == 0x2a && raw[at + 1] == 0xaa
}

#[pyfunction]
fn decode_snapshot<'py>(
    py: Python<'py>,
    raw: &[u8],
    max_pp: &Bound<'py, PyTuple>,
) -> PyResult<Bound<'py, PyDict>> {
    if raw.len() != 0x2000 {
        return Err(PyValueError::new_err("Expected exactly 8192 WRAM bytes"));
    }
    let row = PyDict::new(py);
    row.set_item("party", party(py, raw, max_pp)?)?;
    for (name, address) in [
        ("map", 0xd35e),
        ("x", 0xd362),
        ("y", 0xd361),
        ("badges", 0xd356),
        ("in_battle", 0xd057),
        ("battle_type", 0xd05a),
        ("opponent", 0xd059),
        ("hall_of_fame_count", 0xd5a2),
    ] {
        row.set_item(name, raw[address - 0xc000])?;
    }
    let battle = raw[0x1057];
    row.set_item("enemy_species", if battle != 0 { raw[0xfe5] } else { 0 })?;
    row.set_item("enemy_level", if battle != 0 { raw[0xff3] } else { 0 })?;
    row.set_item("enemy_shiny", wild_shiny(raw))?;
    row.set_item("saffron_open", raw[0x1728] & 64 != 0)?;
    row.set_item("textbox", raw[0x3a0 + 12 * 20] == 0x79)?;
    row.set_item("start_menu", raw[0x3aa] == 0x79 && battle == 0)?;
    row.set_item("active_box", raw[0x15a0] & 0x7f)?;
    row.set_item("playtime", (raw[0x1a41], raw[0x1a43], raw[0x1a44]))?;
    row.set_item("money", bcd(&raw[0x1347..0x134a]))?;
    row.set_item("coins", bcd(&raw[0x15a4..0x15a6]))?;
    row.set_item("player_name", text(&raw[0x1158..0x1163]))?;
    row.set_item("rival_name", text(&raw[0x134a..0x1355]))?;
    row.set_item("hidden_objects", PyBytes::new(py, &raw[0x15a6..0x15c6]))?;
    row.set_item("event_flags", PyBytes::new(py, &raw[0x1747..0x1887]))?;
    let bag = (0..usize::from(raw[0x131d].min(20)))
        .map(|i| (raw[0x131e + i * 2], raw[0x131f + i * 2]))
        .filter(|(id, _)| *id != 0 && *id != 255)
        .collect::<Vec<_>>();
    row.set_item("items", PyTuple::new(py, bag)?)?;
    let boxed =
        (0..usize::from(raw[0x1a80].min(20))).map(|i| (raw[0x1a96 + i * 33], raw[0x1a99 + i * 33]));
    row.set_item("boxed_pokemon", PyTuple::new(py, boxed)?)?;
    let seen = (0..152)
        .filter(|i| raw[0x130a + i / 8] & (1 << (i % 8)) != 0)
        .map(|i| i + 1)
        .collect::<Vec<_>>();
    let owned = seen
        .iter()
        .copied()
        .filter(|i| raw[0x12f7 + (i - 1) / 8] & (1 << ((i - 1) % 8)) != 0)
        .collect::<Vec<_>>();
    row.set_item("seen", PyFrozenSet::new(py, &seen)?)?;
    row.set_item("owned", PyFrozenSet::new(py, &owned)?)?;
    Ok(row)
}

#[pymodule]
fn pokesim_core_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("DECODER_API", 1)?;
    m.add_function(wrap_pyfunction!(decode_snapshot, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn text_terminators_and_symbols() {
        assert_eq!(text(&[0x80, 0x50, 0x81]), "A");
        assert_eq!(text(&[0x7f, 0xe1, 0xe2, 0xba, 0xef, 0x7f]), "PKMNé♂");
        assert_eq!(text(&[0x70, 1, 0xf6, 0]), "?0");
    }

    #[test]
    fn raw_decimal_nibbles_preserve_python_behavior() {
        assert_eq!(bcd(&[0x12, 0x34, 0x56]), 123456);
        assert_eq!(bcd(&[0xfa]), 160);
    }
}
