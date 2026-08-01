"""Offline checks for the category-flows normalize/merge logic (no network)."""
import pandas as pd
from cache_manager import _normalize_flows, _merge_flows


def _raw(date, category, buy, sell, net):
    return pd.DataFrame([{
        'Trade Date': date, 'Category': category,
        'Buy Value in Rs.Crores': buy, 'Sell Value in Rs.Crores': sell,
        'Net Value in Rs.Crores': net,
    }])


def test_label_drift_folds_together():
    old = _normalize_flows(_raw('15-Jan-2024', 'AIFs', 347.2, 207.6, 139.6))
    new = _normalize_flows(_raw('29-Jul-2026', 'AIF', 607.7, 636.3, -28.6))
    assert set(old['category']) == set(new['category']) == {'AIF'}
    assert _normalize_flows(_raw('15-Jan-2024', 'Retail', 1, 2, -1))['category'][0] == 'RETAIL'
    assert _normalize_flows(_raw('15-Jan-2024', 'Insurance Companies', 1, 2, -1))['category'][0] == 'INSURANCE'
    assert _normalize_flows(_raw('05-Aug-2021', 'PRO-TRADES', 1, 2, -1))['category'][0] == 'PRO_TRADES'
    assert old['date'][0] == pd.Timestamp('2024-01-15')


def test_refetch_updates_not_duplicates():
    first = _normalize_flows(_raw('29-Jul-2026', 'FPI', 19839.6, 15195.9, 4643.7))
    revised = _normalize_flows(_raw('29-Jul-2026', 'FPI', 19900.0, 15195.9, 4704.1))
    merged = _merge_flows(first, revised)
    assert len(merged) == 1, "same date+category must collapse to one row"
    assert merged['net_cr'][0] == 4704.1, "the later fetch must win"

    other = _normalize_flows(_raw('29-Jul-2026', 'RETAIL', 44330.8, 48135.8, -3805.0))
    assert len(_merge_flows(merged, other)) == 2


if __name__ == "__main__":
    test_label_drift_folds_together()
    test_refetch_updates_not_duplicates()
    print("category flows: OK")
