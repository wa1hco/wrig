import os
from pathlib import Path

import pytest

from wrig.config import _default_log_dir, _default_wsjtx_binary
from wrig.registry import parse_rig_name


@pytest.mark.skipif(os.name == "nt", reason="Linux/XDG path layout")
def test_wsjtx_paths_linux(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    from wrig.launcher import (wsjtx_config_file_for, wsjtx_base_config_file,
                               wsjtx_log_dir_for)
    # Linux: config is a flat file; log/data is a separate directory.
    assert wsjtx_config_file_for("FOO") == tmp_path / "cfg" / "WSJT-X - FOO.ini"
    assert wsjtx_base_config_file() == tmp_path / "cfg" / "WSJT-X.ini"
    assert wsjtx_log_dir_for("FOO") == tmp_path / "data" / "WSJT-X - FOO"


def test_default_log_dir_paths():
    # The default is a NAS placeholder the user edits; pin the current value
    # so accidental drift is caught.
    if os.name == "nt":
        assert _default_log_dir() == r"\\192.168.1.5\share\wrig"
    else:
        assert _default_log_dir() == "/media/share/wrig"


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
