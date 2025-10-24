import pandas as pd
def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None



# Expected columns (case-insensitive):
# current_assets, inventory, current_liabilities, total_assets, total_equity, total_debt,
# ebit, interest_expense, revenue, gross_profit, net_income, avg_total_assets, avg_total_equity




def _col(df: pd.DataFrame, name: str):
    for c in df.columns:
        if c.lower() == name.lower():
            return df[c]
    return None





def compute_ratios(df: pd.DataFrame) -> pd.DataFrame:
	out = pd.DataFrame(index=df.index)

	ca = _col(df, "current_assets")
	inv = _col(df, "inventory")
	cl = _col(df, "current_liabilities")
	ta = _col(df, "total_assets")
	te = _col(df, "total_equity")
	td = _first(_col(df, "total_debt"), _col(df, "debt"))
	ebit = _col(df, "ebit")
	int_exp = _col(df, "interest_expense")
	rev = _first(_col(df, "revenue"), _col(df, "sales"))
	gp = _col(df, "gross_profit")
	ni = _col(df, "net_income")
	ata = _first(_col(df, "avg_total_assets"), (None if ta is None else ta.rolling(2).mean()))
	ate = _first(_col(df, "avg_total_equity"), (None if te is None else te.rolling(2).mean()))

	# Liquidity
	if ca is not None and cl is not None:
		out["current_ratio"] = ca / cl
	if ca is not None and inv is not None and cl is not None:
		out["quick_ratio"] = (ca - inv) / cl

	# Profitability
	if gp is not None and rev is not None:
		out["gross_margin"] = gp / rev
	if ni is not None and rev is not None:
		out["net_margin"] = ni / rev
	if ni is not None and ata is not None:
		out["roa"] = ni / ata
	if ni is not None and ate is not None:
		out["roe"] = ni / ate

	# Efficiency
	if rev is not None and ata is not None:
		out["asset_turnover"] = rev / ata

	# Leverage
	if td is not None and te is not None:
		out["debt_to_equity"] = td / te
	if td is not None and ta is not None:
		out["debt_ratio"] = td / ta

	# Coverage
	if ebit is not None and int_exp is not None:
		out["interest_coverage"] = ebit / (int_exp.replace(0, pd.NA))

	out.reset_index(drop=True, inplace=True)
	return out