import pandas as pd
from typing import Dict


# Compute a few common KPIs when columns exist
# revenue, cogs, operating_expenses, ebitda, net_income


def compute_kpis(df: pd.DataFrame) -> Dict:
	out = {}
	cols = {c.lower(): c for c in df.columns}

	def _first(*vals):
		for v in vals:
			if v is not None:
				return v
		return None

	def col(name: str):
		key = name.lower()
		return df[cols[key]] if key in cols else None

	revenue = _first(col("revenue"), col("sales"))
	cogs = _first(col("cogs"), col("cost_of_goods_sold"))
	ebitda = _first(col("ebitda"))
	net_income = _first(col("net_income"), col("net income"), col("netincome"))

	# Margins
	if ebitda is not None and revenue is not None and len(revenue) > 0:
		out["ebitda_margin"] = (ebitda / revenue).iloc[-1]

	# Growth (last vs prior)
	def last_growth(series: pd.Series):
		if series is None or len(series) < 2:
			return None
		prev, curr = series.iloc[-2], series.iloc[-1]
		if prev == 0:
			return None
		return (curr - prev) / abs(prev)

	if revenue is not None:
		g = last_growth(revenue)
		if g is not None:
			out["revenue_growth"] = g
	if net_income is not None:
		g = last_growth(net_income)
		if g is not None:
			out["net_income_growth"] = g

	return out