"""Meta-labeling: replace the dead XGBoost return-predictor with a trade filter.

The existing models try to predict the SIZE of the next move and score R2 ~ 0. That is not a
tuning failure - expected returns are tiny next to their own noise, so the magnitude is
close to unlearnable and every downstream decision inherits that false precision.

Meta-labeling reframes it. The primary rule (RSI<30 + liquidity floor) still decides the
SIDE. A second model answers a much easier, binary question:

    given this signal fired, what is P(this trade ends profitable)?

That is a classification problem with a ~54% base rate, and the answer is directly usable -
it sizes the bet and filters the weakest setups. Trained with purged, chronological splits so
overlapping labels cannot leak between train and test.

Ships ONLY if it beats the base rate out of sample. If it does not, it gets deleted and the
null result recorded - the same standard the README already applies to the XGBoost models.
"""

import os
import pickle
import numpy as np
import pandas as pd

from config import BASE_DIR, CAP_BUCKET_MAP, MIN_TURNOVER_INR
from backtest_engine import simulate_trades

META_MODEL_PATH = os.path.join(BASE_DIR, "meta_model_short.pkl")

# Features known at entry time. No forward-looking columns.
META_FEATURES = ['rsi', 'atr_pct', 'distance_from_high_50', 'change_252d',
                 'volume_change', 'macd_hist', 'px_vs_sma20', 'px_vs_sma50', 'log_turnover']


def build_feature_frame(sub):
    """Derive meta-features from a stock frame. Ratios, not raw levels, so they are
    comparable across stocks at different price scales."""
    f = pd.DataFrame(index=sub.index)
    f['rsi'] = sub['rsi']
    f['atr_pct'] = sub['atr_pct']
    f['distance_from_high_50'] = sub['distance_from_high_50']
    f['change_252d'] = sub['change_252d']
    f['volume_change'] = sub['volume_change'].clip(-5, 5)
    f['macd_hist'] = (sub['macd'] - sub['macd_signal']) / sub['close'] * 100
    f['px_vs_sma20'] = sub['close'] / sub['sma_20'] - 1
    f['px_vs_sma50'] = sub['close'] / sub['sma_50'] - 1
    f['log_turnover'] = np.log10(sub['turnover_60d'].clip(lower=1e5))
    return f


def build_dataset(dataset_path='cache/backtest_5y_short.pkl', rsi_threshold=30):
    """One row per trade the primary rule would have taken, labelled win/loss."""
    with open(dataset_path, 'rb') as fh:
        d = pickle.load(fh)

    rows, labels, dates = [], [], []
    for t, df in d.items():
        if CAP_BUCKET_MAP.get(t) == 'Large':
            continue
        sub = df.dropna(subset=['rsi', 'atr', 'close', 'sma_20', 'sma_50']).reset_index(drop=True)
        if len(sub) < 100:
            continue
        liq = (sub['turnover_60d'] >= MIN_TURNOVER_INR).fillna(False).values
        mask = (sub['rsi'] < rsi_threshold).values & liq
        trades = simulate_trades(sub, mask, charge_costs=True)
        if not trades:
            continue
        feats = build_feature_frame(sub)
        for tr in trades:
            row = feats.iloc[tr['entry_idx']]
            if row.isna().any():
                continue
            rows.append(row.values)
            labels.append(1 if tr['net_pct'] > 0 else 0)
            dates.append(sub['date'].iat[tr['entry_idx']])

    X = pd.DataFrame(rows, columns=META_FEATURES)
    y = pd.Series(labels, name='win')
    order = np.argsort(pd.to_datetime(pd.Series(dates)).values)  # chronological
    return X.iloc[order].reset_index(drop=True), y.iloc[order].reset_index(drop=True), \
        pd.Series(dates).iloc[order].reset_index(drop=True)


def purged_splits(n, n_splits=4, embargo=20):
    """Chronological expanding-window splits with an embargo gap.

    The gap matters: a 6-day label straddling the boundary would otherwise put the same
    forward returns in both train and test, which is how a useless model tests well.
    """
    fold = n // (n_splits + 1)
    for k in range(1, n_splits + 1):
        train_end = fold * k
        test_start, test_end = train_end + embargo, min(train_end + embargo + fold, n)
        if test_end - test_start < 50:
            continue
        yield np.arange(0, train_end), np.arange(test_start, test_end)


def train_and_evaluate(verbose=True):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score

    X, y, dates = build_dataset()
    base_rate = y.mean()
    if verbose:
        print(f"dataset: {len(X)} trades, base win rate {base_rate*100:.1f}%")

    aucs, lifts, coverage = [], [], []
    for tr_idx, te_idx in purged_splits(len(X)):
        model = RandomForestClassifier(
            n_estimators=300, max_depth=4, min_samples_leaf=50,
            class_weight='balanced', random_state=0, n_jobs=-1)
        model.fit(X.iloc[tr_idx], y.iloc[tr_idx])
        p = model.predict_proba(X.iloc[te_idx])[:, 1]
        yte = y.iloc[te_idx].values

        auc = roc_auc_score(yte, p) if len(np.unique(yte)) > 1 else 0.5
        # Does taking only the top-scoring half actually win more often?
        cut = np.median(p)
        top = yte[p >= cut]
        aucs.append(auc)
        lifts.append(top.mean() - yte.mean() if len(top) else 0.0)
        coverage.append(len(top) / len(yte))

    mean_auc, mean_lift = float(np.mean(aucs)), float(np.mean(lifts))
    if verbose:
        print(f"purged CV folds: {len(aucs)}")
        print(f"  mean AUC            : {mean_auc:.4f}   (0.50 = no information)")
        print(f"  mean win-rate lift  : {mean_lift*100:+.2f} pp on the top half of scores")
        print(f"  per-fold AUC        : {[round(a,3) for a in aucs]}")

    # Ship criteria, decided before looking: the model must carry information (AUC > 0.53)
    # AND actually improve the win rate of the trades it selects (lift > 1pp).
    passed = mean_auc > 0.53 and mean_lift > 0.01
    if verbose:
        print(f"\nVERDICT: {'PASS - worth shipping' if passed else 'FAIL - does not beat the base rate'}")
    return {'auc': mean_auc, 'lift': mean_lift, 'base_rate': float(base_rate),
            'passed': passed, 'n': len(X), 'coverage': float(np.mean(coverage))}


_LOADED = None


def load_meta_model():
    """Cached load. Returns None if the model was never trained or failed its ship criteria,
    so callers degrade to no meta-score rather than crashing."""
    global _LOADED
    if _LOADED is None:
        if not os.path.exists(META_MODEL_PATH):
            _LOADED = False
        else:
            try:
                with open(META_MODEL_PATH, 'rb') as fh:
                    _LOADED = pickle.load(fh)
            except Exception:
                _LOADED = False
    return _LOADED or None


def score_latest(sub):
    """P(this trade ends profitable) for the most recent bar of a stock frame.

    Returns None when the model is unavailable or features are incomplete - the caller must
    treat a missing score as "no opinion", never as a low score.
    """
    bundle = load_meta_model()
    if bundle is None:
        return None
    try:
        feats = build_feature_frame(sub).iloc[[-1]]
        if feats.isna().any(axis=None):
            return None
        return float(bundle['model'].predict_proba(feats[bundle['features']])[0, 1])
    except Exception:
        return None


def fit_final_model():
    """Fit on all data and persist. Only call after train_and_evaluate() passes."""
    from sklearn.ensemble import RandomForestClassifier
    X, y, _ = build_dataset()
    model = RandomForestClassifier(n_estimators=300, max_depth=4, min_samples_leaf=50,
                                   class_weight='balanced', random_state=0, n_jobs=-1)
    model.fit(X, y)
    with open(META_MODEL_PATH, 'wb') as fh:
        pickle.dump({'model': model, 'features': META_FEATURES}, fh)
    return META_MODEL_PATH


if __name__ == "__main__":
    res = train_and_evaluate()
    if res['passed']:
        print(f"saved -> {fit_final_model()}")
    else:
        print("Model NOT saved. Recording the null result rather than shipping a weak signal.")
