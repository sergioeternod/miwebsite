import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(close: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1000,
        }
    )
    df.index = pd.date_range("2023-01-01", periods=len(df), freq="D")
    df.index.name = "Date"
    return df


@pytest.fixture
def uptrend_df() -> pd.DataFrame:
    close = pd.Series(np.linspace(100, 200, 120))
    return _make_ohlcv(close)


@pytest.fixture
def downtrend_df() -> pd.DataFrame:
    close = pd.Series(np.linspace(200, 100, 120))
    return _make_ohlcv(close)


@pytest.fixture
def random_walk_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 400
    returns = rng.normal(0.0006, 0.02, n)
    close = 100 * (1 + pd.Series(returns)).cumprod()
    return _make_ohlcv(close)
