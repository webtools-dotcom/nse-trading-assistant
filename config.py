import pandas as pd

def load_watchlist():
    df = pd.read_csv('nse_watchlist_expanded.csv')
    return df['ticker'].tolist()

WATCHLIST = load_watchlist()

def load_cap_bucket_map():
    df = pd.read_csv('nse_watchlist_expanded.csv')
    return dict(zip(df['ticker'], df['cap_bucket']))

CAP_BUCKET_MAP = load_cap_bucket_map()

# --- SHORT-TERM (4-6 day) settings - validated: RSI<30 + ATR stops, z-score 8.08 ---
SHORT_FEATURE_COLUMNS = ['rsi', 'macd', 'macd_signal', 'sma_20', 'sma_50',
                          'volume_change', 'price_change', 'volatility_10',
                          'distance_from_high_50', 'atr_pct']
SHORT_MODEL_PATH = "trading_model_short.pkl"
SHORT_HORIZON_DAYS = 6

# --- LONG-TERM (1-month) settings - validated: near 52w high + uptrend, z-score 9.69 ---
LONG_FEATURE_COLUMNS = ['rsi', 'sma_50', 'sma_200', 'momentum_60d', 'dist_from_high_252',
                         'volume_change', 'price_change', 'atr_pct']
LONG_MODEL_PATH = "trading_model_long.pkl"
LONG_HORIZON_DAYS = 20
LONG_STOP_PCT = 0.08
LONG_TARGET_PCT = 0.16

DEFAULT_CAPITAL = 5000
DEFAULT_RISK_PCT = 1

# ============================================
# PROVIDER PRESETS
# ============================================
PROVIDERS = {
    "groq":       {"base_url": "https://api.groq.com/openai/v1",   "key_env": "GROQ_API_KEY",     "model": "qwen/qwen3.6-27b"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",       "key_env": "DEEPSEEK_API_KEY", "model": "deepseek-chat"},
    "minimax":    {"base_url": "https://api.minimax.io/v1",         "key_env": "MINIMAX_API_KEY",  "model": "MiniMax-M2.5"},
    "anthropic":  {"base_url": "https://api.anthropic.com/v1/",     "key_env": "ANTHROPIC_API_KEY","model": "claude-sonnet-4-6"},
    "local_ollama": {"base_url": "http://localhost:11434/v1",       "key_env": None,               "model": "qwen3.5:9b"},
    "kaggle_ngrok": {"base_url": "https://YOUR-NGROK-URL.ngrok-free.app/v1", "key_env": None,       "model": "qwen3.6:35b-a3b"},
    "google":       {"base_url": "https://api.google.com/v1",   "key_env": "GOOGLE_API_KEY",     "model": "openai/gpt-oss-120b"},

}
ACTIVE_PROVIDER = "groq"