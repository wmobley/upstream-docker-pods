import pandas as pd

from app.utils.upload_csv import normalize_legacy_sensor_columns


def test_normalize_legacy_sensor_columns_renames_bestguessformula():
    df = pd.DataFrame(
        {
            "alias": ["V"],
            "BestGuessFormula": ["Voltage"],
            "postprocess": [False],
            "units": ["volts"],
        }
    )

    normalized = normalize_legacy_sensor_columns(df)

    assert "variablename" in normalized.columns
    assert "BestGuessFormula" not in normalized.columns
    assert normalized.loc[0, "variablename"] == "Voltage"


def test_normalize_legacy_sensor_columns_prefers_existing_variablename():
    df = pd.DataFrame(
        {
            "alias": ["V"],
            "BestGuessFormula": ["Voltage (legacy)"],
            "variablename": ["Voltage"],
        }
    )

    normalized = normalize_legacy_sensor_columns(df)

    assert normalized.loc[0, "variablename"] == "Voltage"
    assert normalized.loc[0, "BestGuessFormula"] == "Voltage (legacy)"


def test_normalize_legacy_sensor_columns_noop_without_legacy_header():
    df = pd.DataFrame({"alias": ["V"], "units": ["volts"]})

    normalized = normalize_legacy_sensor_columns(df)

    assert list(normalized.columns) == list(df.columns)
