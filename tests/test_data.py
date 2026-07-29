import pytest

from app.data.providers import DataUnavailableError, filter_date_range
from app.data.synthetic import generate_ohlcv, regimes_for_range


def test_filter_date_range_no_bounds_returns_same_df(random_walk_df):
    result = filter_date_range(random_walk_df)
    assert len(result) == len(random_walk_df)


def test_filter_date_range_slices_inclusive(random_walk_df):
    start = str(random_walk_df.index[10].date())
    end = str(random_walk_df.index[20].date())
    result = filter_date_range(random_walk_df, start, end)
    assert len(result) == 11
    assert str(result.index[0].date()) == start
    assert str(result.index[-1].date()) == end


def test_filter_date_range_empty_window_raises(random_walk_df):
    with pytest.raises(DataUnavailableError):
        filter_date_range(random_walk_df, "2099-01-01", "2099-12-31")


def test_regimes_for_range_full_df_matches_generation():
    df = generate_ohlcv(seed=1)
    regime_dates = df.attrs["regimes"]
    positions = regimes_for_range(df, regime_dates)
    assert len(positions) == len(regime_dates)
    for name, start_idx, end_idx in positions:
        assert 0 <= start_idx <= end_idx < len(df)


def test_regimes_for_range_drops_regimes_outside_window():
    df = generate_ohlcv(seed=1)
    regime_dates = df.attrs["regimes"]
    # Window entirely inside the first regime ("alza sostenida", ~90 days).
    windowed = filter_date_range(df, str(df.index[0].date()), str(df.index[10].date()))
    positions = regimes_for_range(windowed, regime_dates)
    assert len(positions) == 1
    assert positions[0][0] == regime_dates[0][0]
