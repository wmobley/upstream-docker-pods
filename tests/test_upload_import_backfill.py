import pytest

from app.services.upload_import_backfill_service import (
    _quote_identifier,
    _shadow_index_name,
    _table_names,
)


def test_backfill_table_names_are_uuid_scoped_and_index_name_is_postgres_safe():
    raw, shadow = _table_names("12345678-1234-5678-1234-567812345678")

    assert raw == "upload_backfill_raw_12345678123456781234567812345678"
    assert shadow == "upload_backfill_shadow_12345678123456781234567812345678"
    assert len(_shadow_index_name(shadow)) <= 63
    assert _quote_identifier(raw).startswith('"upload_backfill_raw_')


def test_backfill_identifier_helper_rejects_untrusted_sql_identifiers():
    with pytest.raises(ValueError):
        _quote_identifier('raw_table"; DROP TABLE measurements; --')
