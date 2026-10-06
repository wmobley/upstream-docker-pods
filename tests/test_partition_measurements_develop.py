from pathlib import Path

import importlib.util


SCRIPT = Path(__file__).parents[1] / "scripts" / "partition_measurements_develop.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("partition_measurements_develop", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_uses_hash_partition_routing_and_explicit_columns() -> None:
    module = _load_script()

    assert module.PARTITION_COUNT == 16
    assert "satisfies_hash_partition" in module._partition_predicate()
    assert "::regclass" in module._partition_predicate()
    assert ":remainder" in module._partition_predicate()
    assert "measurementid" in module.COPY_COLUMNS
    assert "geometry" in module.COPY_COLUMNS


def test_partition_and_index_cursors_are_bounded_and_deterministic() -> None:
    module = _load_script()

    assert module._partition_table_name(0).endswith("_p0")
    assert module._partition_table_name(module.PARTITION_COUNT - 1).endswith("_p15")
    assert module._local_index_name("pkey", 0).endswith("_pkey_idx")
    assert len(module.INDEX_KEYS) * module.PARTITION_COUNT == 48

    for invalid in (-1, module.PARTITION_COUNT):
        try:
            module._partition_table_name(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"remainder {invalid} should be rejected")


def test_prepare_is_resumable_and_attaches_partition_indexes() -> None:
    source = SCRIPT.read_text()

    assert "copy_cursor INTEGER NOT NULL DEFAULT -1" in source
    assert "index_cursor INTEGER NOT NULL DEFAULT -1" in source
    assert "range(int(copy_cursor) + 1, PARTITION_COUNT)" in source
    assert "range(int(index_cursor) + 1, PARTITION_COUNT * len(INDEX_KEYS))" in source
    assert "ON ONLY" in source
    assert "ATTACH PARTITION" in source
    assert "CREATE TRIGGER" in source
    assert "pg_trigger" in source


def test_prepare_no_longer_runs_one_unbounded_shadow_copy() -> None:
    source = SCRIPT.read_text()

    assert "INSERT INTO {target} ({COPY_COLUMNS})" in source
    assert "WHERE {_partition_predicate()}" in source
    assert "_copy_and_index" not in source
