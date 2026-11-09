"""The setup script: which steps it runs, and what it downloads (no network: a download here is a local file)."""

import importlib.util
import pathlib
import zipfile

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "setup.py"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    spec = importlib.util.spec_from_file_location("homecare_setup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def names(steps):
    return [step.name for step in steps]


def test_on_a_new_clone_every_step_runs(setup, tmp_path):
    assert names(setup.choose(setup.steps(tmp_path), None)) == \
        ["osm", "addresses", "streets", "osrm", "gtfs", "java", "map"]


def test_steps_already_done_are_skipped(setup, tmp_path):
    (tmp_path / "data" / "osm").mkdir(parents=True)
    (tmp_path / "data" / "osm" / "new-york-latest.osm.pbf").touch()
    (tmp_path / "data" / "gtfs").mkdir()
    for feed in setup.GTFS_FEEDS:
        (tmp_path / "data" / "gtfs" / f"gtfs_{feed}.zip").touch()
    (tmp_path / "tools" / "jdk-21.0.13+9").mkdir(parents=True)
    for mode in setup.OSRM_PROFILES:
        (tmp_path / "data" / "osrm" / mode).mkdir(parents=True)
        (tmp_path / "data" / "osrm" / mode / "map.osrm.cell_metrics").touch()
    assert names(setup.choose(setup.steps(tmp_path), None)) == ["addresses", "streets", "map"]


def test_a_road_network_is_done_only_when_both_are(setup, tmp_path):
    (tmp_path / "data" / "osrm" / "walking").mkdir(parents=True)
    (tmp_path / "data" / "osrm" / "walking" / "map.osrm.cell_metrics").touch()
    assert "osrm" in names(setup.choose(setup.steps(tmp_path), None))


def test_java_is_not_downloaded_when_java_home_is_set(setup, tmp_path, monkeypatch):
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    assert "java" not in names(setup.choose(setup.steps(tmp_path), None))


def test_only_runs_the_steps_named_and_needs_their_map(setup, tmp_path):
    assert names(setup.choose(setup.steps(tmp_path), "map, gtfs")) == ["gtfs", "map"]
    assert names(setup.choose(setup.steps(tmp_path), "osm,addresses")) == ["osm", "addresses"]
    with pytest.raises(setup.SetupError, match="addresses needs step osm"):
        setup.choose(setup.steps(tmp_path), "addresses")
    with pytest.raises(setup.SetupError, match="no step roads"):
        setup.choose(setup.steps(tmp_path), "roads")


def test_the_map_needs_every_font_file(setup):
    files = setup.font_files()
    assert len(files) == 3 * 256 + 1
    assert "fonts/Noto Sans Medium/65280-65535.pbf" in files


def test_the_pmtiles_tool_for_each_computer(setup):
    assert setup.pmtiles_asset("windows", "x64") == "go-pmtiles_1.31.2_Windows_x86_64.zip"
    assert setup.pmtiles_asset("linux", "arm64") == "go-pmtiles_1.31.2_Linux_arm64.tar.gz"
    assert setup.pmtiles_asset("mac", "arm64") == "go-pmtiles-1.31.2_Darwin_arm64.zip"


def test_the_newest_world_map_is_used(setup):
    builds = [{"key": "20261030.pmtiles"}, {"key": "20261106.pmtiles"}, {"key": "20261102.pmtiles"}]
    assert setup.latest_build(builds) == "20261106.pmtiles"


def test_a_download_is_whole_or_not_there(setup, tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"x" * 3_000_000)
    target = tmp_path / "data" / "file.bin"
    setup.download(source.as_uri(), target, quiet=True)
    assert target.read_bytes() == source.read_bytes()
    assert not (tmp_path / "data" / "file.bin.part").exists()


def test_an_archive_is_unpacked_into_a_folder_of_its_own(setup, tmp_path):
    archive = tmp_path / "tool.zip"
    with zipfile.ZipFile(archive, "w") as files:
        files.writestr("jdk-21/bin/java", "")
    folder = setup.unpack(archive, tmp_path / "unpacked")
    assert (folder / "jdk-21" / "bin" / "java").exists()
