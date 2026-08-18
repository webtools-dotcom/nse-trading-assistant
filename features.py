import numpy as np
import ta

MIN_BARS = 100  # aligned across cache and training paths - see CLAUDE.md pattern #4


def _scrub(df):
    return df.replace([np.inf, -np.inf], np.nan)


def add_short_features(stock_df):
    """Short-term feature set - validated for 4-6 day horizon (RSI<30, z-score 8.08)."""
    stock_df = stock_df.sort_values('date').reset_index(drop=True)

    stock_df['rsi'] = ta.momentum.RSIIndicator(close=stock_df['close'], window=14).rsi()
    macd = ta.trend.MACD(close=stock_df['close'])
    stock_df['macd'] = macd.macd()
    stock_df['macd_signal'] = macd.macd_signal()
    stock_df['ema_10'] = ta.trend.EMAIndicator(close=stock_df['close'], window=10).ema_indicator()
    stock_df['ema_20'] = ta.trend.EMAIndicator(close=stock_df['close'], window=20).ema_indicator()
    stock_df['sma_20'] = ta.trend.SMAIndicator(close=stock_df['close'], window=20).sma_indicator()
    stock_df['sma_50'] = ta.trend.SMAIndicator(close=stock_df['close'], window=50).sma_indicator()
    stock_df['sma_200'] = ta.trend.SMAIndicator(close=stock_df['close'], window=200).sma_indicator()
    stock_df['volume_change'] = stock_df['volume'].pct_change()
    stock_df['price_change'] = stock_df['close'].pct_change()
    # median beats mean here - one block deal shouldn't make an illiquid stock look tradeable
    stock_df['turnover_60d'] = (stock_df['close'] * stock_df['volume']).rolling(60).median()
    stock_df['volatility_10'] = stock_df['close'].rolling(10).std()
    stock_df['distance_from_high_50'] = (stock_df['close'] / stock_df['close'].rolling(50).max()) - 1
    stock_df['dist_from_high_252'] = (stock_df['close'] / stock_df['close'].rolling(252).max()) - 1
    stock_df['momentum_60d'] = stock_df['close'].pct_change(60) * 100
    stock_df['change_252d'] = stock_df['close'].pct_change(252) * 100

    atr_indicator = ta.volatility.AverageTrueRange(high=stock_df['high'], low=stock_df['low'], close=stock_df['close'], window=14)
    stock_df['atr'] = atr_indicator.average_true_range()
    stock_df['atr_pct'] = (stock_df['atr'] / stock_df['close']) * 100

    # Breakout / VCP Volatility Contraction indicators
    atr_5_ind = ta.volatility.AverageTrueRange(high=stock_df['high'], low=stock_df['low'], close=stock_df['close'], window=5)
    atr_20_ind = ta.volatility.AverageTrueRange(high=stock_df['high'], low=stock_df['low'], close=stock_df['close'], window=20)
    stock_df['atr_5'] = atr_5_ind.average_true_range()
    stock_df['atr_20'] = atr_20_ind.average_true_range()
    stock_df['vcp_ratio'] = stock_df['atr_5'] / stock_df['atr_20']
    stock_df['base_high_5d'] = stock_df['high'].rolling(5).max()
    stock_df['base_low_5d'] = stock_df['low'].rolling(5).min()
    stock_df['base_depth_pct'] = ((stock_df['base_high_5d'] - stock_df['base_low_5d']) / stock_df['base_high_5d']) * 100
    vol_sma_20 = stock_df['volume'].rolling(20).mean()
    stock_df['rvol'] = stock_df['volume'] / vol_sma_20.replace(0, np.nan)

    return _scrub(stock_df)


def add_long_features(stock_df):
    """Long-term feature set - validated for 1-2 month horizons via backtest_longterm.py"""
    stock_df = stock_df.sort_values('date').reset_index(drop=True)

    stock_df['rsi'] = ta.momentum.RSIIndicator(close=stock_df['close'], window=14).rsi()
    stock_df['sma_50'] = ta.trend.SMAIndicator(close=stock_df['close'], window=50).sma_indicator()
    stock_df['sma_200'] = ta.trend.SMAIndicator(close=stock_df['close'], window=200).sma_indicator()
    stock_df['momentum_60d'] = stock_df['close'].pct_change(60) * 100
    stock_df['dist_from_high_252'] = (stock_df['close'] / stock_df['close'].rolling(252).max()) - 1
    stock_df['volume_change'] = stock_df['volume'].pct_change()
    stock_df['price_change'] = stock_df['close'].pct_change()
    # median beats mean here - one block deal shouldn't make an illiquid stock look tradeable
    stock_df['turnover_60d'] = (stock_df['close'] * stock_df['volume']).rolling(60).median()

    atr_indicator = ta.volatility.AverageTrueRange(high=stock_df['high'], low=stock_df['low'], close=stock_df['close'], window=14)
    stock_df['atr'] = atr_indicator.average_true_range()
    stock_df['atr_pct'] = (stock_df['atr'] / stock_df['close']) * 100

    return _scrub(stock_df)


def demo():
    import pandas as pd
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.normal(0, 1, len(dates)).cumsum())
    df = pd.DataFrame({
        'date': dates, 'open': close, 'high': close + 1, 'low': close - 1,
        'close': close, 'volume': [0] + [100] * (len(dates) - 1),  # zero volume bar -> pct_change inf, must be scrubbed
    })

    short = add_short_features(df.copy())
    assert not np.isinf(short['volume_change']).any(), "inf leaked into volume_change"
    assert 'change_252d' in short.columns
    assert short['turnover_60d'].notna().any(), "turnover_60d never populated"

    long = add_long_features(df.copy())
    assert not np.isinf(long['volume_change']).any(), "inf leaked into volume_change"
    assert 'momentum_60d' in long.columns
    assert long['turnover_60d'].notna().any(), "turnover_60d never populated"
    print("features.py self-check passed")


if __name__ == "__main__":
    demo()
