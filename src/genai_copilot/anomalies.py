import pandas as pd
import numpy as np


NUMERIC_GROWTH_CANDIDATES = [
"revenue", "gross_profit", "ebit", "net_income", "total_assets", "total_equity",
]




def _safe_cols(df: pd.DataFrame, cols):
	found = []
	for c in cols:
		m = [x for x in df.columns if x.lower() == c]
		if m:
			found.append(m[0])
	return found




def zscore_outliers(series: pd.Series, thresh: float = 3.0):
	std = series.std(ddof=0)
	if std == 0 or pd.isna(std):
		return pd.Series([False] * len(series), index=series.index)
	z = (series - series.mean()) / std
	return (z.abs() >= thresh)




def detect_anomalies(df: pd.DataFrame) -> dict:
	report = {"outliers": {}, "spikes": {}}

	# Outliers across numeric columns
	for c in df.select_dtypes(include=[np.number]).columns:
		mask = zscore_outliers(df[c].astype(float))
		if mask.any():
			report["outliers"][c] = df.loc[mask, c].index.tolist()

	# Growth spikes on common metrics (±25% QoQ/YoY depending on your rows)
	for c in _safe_cols(df, [x.lower() for x in NUMERIC_GROWTH_CANDIDATES]):
		s = df[c].astype(float)
		growth = s.pct_change()
		spike_idx = growth[growth.abs() >= 0.25].index.tolist()
		if spike_idx:
			report["spikes"][c] = {"threshold": 0.25, "rows": spike_idx}

	return report