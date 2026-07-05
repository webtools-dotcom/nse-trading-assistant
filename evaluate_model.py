import pickle
from sklearn.metrics import mean_absolute_error, r2_score
from data_fetcher import build_training_dataset
from config import WATCHLIST, FEATURE_COLUMNS, MODEL_PATH

def evaluate():
    print("Rebuilding dataset for evaluation (same process as training)...")
    full_df_clean = build_training_dataset(WATCHLIST, period="5y", horizon=4)
    print(f"Dataset ready: {len(full_df_clean)} rows")

    cutoff_date = full_df_clean['date'].quantile(0.8)
    test_df = full_df_clean[full_df_clean['date'] >= cutoff_date]

    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df['target_pct_capped']

    with open(MODEL_PATH, 'rb') as f:
        model = pickle.load(f)

    predictions = model.predict(X_test)

    mae = mean_absolute_error(y_test, predictions)
    r2 = r2_score(y_test, predictions)

    direction_actual = (y_test > 0).astype(int)
    direction_predicted = (predictions > 0).astype(int)
    direction_accuracy = (direction_actual == direction_predicted).mean()

    print(f"\n{'='*40}")
    print(f"EVALUATION RESULTS ({len(test_df)} test rows)")
    print(f"{'='*40}")
    print(f"Mean Absolute Error: {mae:.2f}%")
    print(f"R² Score: {r2:.4f}")
    print(f"Direction accuracy: {direction_accuracy:.2%}")
    print(f"{'='*40}")

if __name__ == "__main__":
    evaluate()