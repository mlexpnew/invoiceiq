import pandas as pd
from typing import Dict


TEMPLATES = {
"default": (
"Top takeaways: {bullets}\n\n"
"Liquidity & Leverage: Current ratio {cr:.2f} and D/E {de:.2f} suggest {liq_msg}. "
"Profitability: Net margin {nm:.1%}, ROE {roe:.1%}. "
"Efficiency: Asset turnover {ato:.2f}."
)
}




def _get_float(d: Dict, key: str, default=float("nan")):
	try:
		v = d.get(key)
		if v is None:
			return default
		return float(v)
	except Exception:
		return default




def make_commentary(kpis: Dict, ratios: pd.DataFrame, template: str = "default") -> str:
	row = ratios.tail(1).to_dict(orient="records")[0] if not ratios.empty else {}
	cr = _get_float(row, "current_ratio")
	de = _get_float(row, "debt_to_equity")
	nm = _get_float(row, "net_margin")
	roe = _get_float(row, "roe")
	ato = _get_float(row, "asset_turnover")

	liq_msg = (
		"solid short-term coverage" if cr >= 1.5 else
		"tight working capital" if cr < 1.0 else
		"adequate liquidity"
	)

	bullets = []
	if "revenue_growth" in kpis:
		bullets.append(f"Revenue growth {kpis['revenue_growth']:.1%} YoY")
	if "ebitda_margin" in kpis:
		bullets.append(f"EBITDA margin {kpis['ebitda_margin']:.1%}")
	if "net_income_growth" in kpis:
		bullets.append(f"Net income growth {kpis['net_income_growth']:.1%}")

	bullets = " • ".join(bullets) if bullets else "Stable performance with limited disclosed KPIs."

	return TEMPLATES[template].format(
		bullets=bullets, cr=cr, de=de, nm=nm, roe=roe, ato=ato, liq_msg=liq_msg
	)