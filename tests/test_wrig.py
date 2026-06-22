import os
from pathlib import Path

from wrig.config import _default_log_dir, _default_wsjtx_binary
from wrig.registry import parse_rig_name


def test_default_log_dir_paths():
    # The default path should be what the current platform expects.
    if os.name == "nt":
        assert _default_log_dir() == r"\\192.168.1.5\Users\share"
    else:
        assert _default_log_dir() == "/mnt/Users/share"


def test_default_wsjtx_binary_exists_or_fallback():
    binary = _default_wsjtx_binary()
    assert isinstance(binary, str)
    assert binary != ""


def test_parse_rig_name_radio_mode():
    radio, band, mode = parse_rig_name("flexa-ft8")
    assert radio == "flexa"
    assert band == ""
    assert mode == "ft8"


def test_parse_rig_name_radio_band_mode():
    radio, band, mode = parse_rig_name("ic7300-2m-ft8")
    assert radio == "ic7300"
    assert band == "2m"
    assert mode == "ft8"


def test_parse_rig_name_complex_radio():
    radio, band, mode = parse_rig_name("my-radio-70cm-q65")
    assert radio == "my-radio"
    assert band == "70cm"
    assert mode == "q65"
