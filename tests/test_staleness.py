from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.campaign_service import CampaignService, summarize_freshness
from app.services.staleness import expected_interval_minutes, is_station_stale, stale_after

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
START = NOW - timedelta(days=10)
END = NOW + timedelta(days=10)


def stale(age: timedelta, meta=None, start=START, end=END) -> bool:
    return is_station_stale(NOW - age, meta, start, end, now=NOW)


def test_default_threshold_is_48_hours():
    assert not stale(timedelta(hours=47))
    assert stale(timedelta(hours=49))


def test_threshold_is_three_expected_intervals():
    meta = {"expected_interval_minutes": 60}
    assert stale_after(meta) == timedelta(hours=3)
    assert not stale(timedelta(hours=2, minutes=59), meta)
    assert stale(timedelta(hours=3, minutes=1), meta)


def test_invalid_interval_falls_back_to_default():
    for bad in (None, "abc", 0, -5, True, {}):
        assert expected_interval_minutes({"expected_interval_minutes": bad}) is None
    assert not stale(timedelta(hours=47), {"expected_interval_minutes": "abc"})


def test_numeric_string_interval_is_accepted():
    assert expected_interval_minutes({"expected_interval_minutes": "30"}) == 30


def test_never_stale_after_campaign_ends():
    assert not stale(timedelta(days=30), end=NOW - timedelta(days=1))


def test_never_stale_before_campaign_starts():
    assert not stale(timedelta(days=30), start=NOW + timedelta(days=1))


def test_open_ended_campaign_is_checked():
    assert stale(timedelta(days=30), end=None)


def test_station_without_data_is_not_stale():
    assert not is_station_stale(None, None, START, END, now=NOW)


def test_naive_datetimes_are_treated_as_utc():
    naive_last = (NOW - timedelta(days=5)).replace(tzinfo=None)
    assert is_station_stale(naive_last, None, START.replace(tzinfo=None), None, now=NOW)


def test_summarize_freshness_counts_stale_stations_and_newest_time():
    # summarize_freshness uses the real clock, so anchor everything to it.
    start = datetime.now(timezone.utc) - timedelta(days=60)
    stations = [
        ({}, datetime.now(timezone.utc) - timedelta(hours=1)),
        ({}, datetime.now(timezone.utc) - timedelta(days=8)),
        ({}, None),
    ]
    newest, stale_count = summarize_freshness(stations, start, None)
    assert stale_count == 1
    assert newest is not None and datetime.now(timezone.utc) - newest < timedelta(hours=2)


def test_summarize_freshness_empty_campaign():
    assert summarize_freshness([], None, None) == (None, 0)


def test_campaign_detail_summary_includes_freshness():
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    long_ago = datetime.now(timezone.utc) - timedelta(days=9)
    repo = Mock()
    repo.get_campaign.return_value = SimpleNamespace(
        campaignid=6,
        campaignname="Bethel",
        description=None,
        contactname=None,
        contactemail=None,
        startdate=datetime.now(timezone.utc) - timedelta(days=90),
        enddate=None,
        allocation=None,
        bbox_west=None,
        bbox_east=None,
        bbox_south=None,
        bbox_north=None,
        geometry=None,
        stations=[],
        meta=None,
    )
    repo.count_stations.return_value = 2
    repo.count_sensors.return_value = 0
    repo.get_sensor_types.return_value = []
    repo.get_sensor_variables.return_value = []
    repo.get_station_freshness.return_value = [
        (6, 20, {"expected_interval_minutes": 60}, recent),
        (6, 23, {"expected_interval_minutes": 60}, long_ago),
    ]

    summary = CampaignService(repo).get_campaign_with_summary(6).summary

    assert summary.stale_station_count == 1
    assert summary.last_measurement_time == recent
    repo.get_station_freshness.assert_called_once_with([6])
