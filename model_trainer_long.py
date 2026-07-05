import pickle
from xgboost import XGBRegressor
from data_fetcher_long import build_training_dataset
from config import WATCHLIST, LONG_FEATURE_COLUMNS, LONG_MODEL_PATH, LONG_HORIZON_DAYS

def train_and_save_model():
    print("Building LONG-TERM training dataset...")
    full_df_clean = build_training_dataset(WATCHLIST, period="5y", horizon=LONG_HORIZON_DAYS)
    print(f"Dataset ready: {len(full_df_clean)} rows")

    cutoff_date = full_df_clean['date'].quantile(0.8)
    train_df = full_df_clean[full_df_clean['date'] < cutoff_date]

    X_train = train_df[LONG_FEATURE_COLUMNS]
    y_train = train_df['target_pct_capped']

    print("Training model...")
    model = XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42)
    model.fit(X_train, y_train)

    with open(LONG_MODEL_PATH, 'wb') as f:
        pickle.dump(model, f)
    print(f"Model saved to {LONG_MODEL_PATH}")

if __name__ == "__main__":
    train_and_save_model()