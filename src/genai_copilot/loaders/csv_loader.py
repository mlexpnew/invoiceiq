import pandas as pd
import io




def read_csv_bytes(b: bytes) -> pd.DataFrame:
	# Try common separators to be forgiving
	for sep in [",", ";", "\t", "|"]:
		try:
			df = pd.read_csv(io.BytesIO(b), sep=sep, engine="python")
			# heuristic: if we get more than one column or comma worked, accept
			if df.shape[1] > 1 or sep == ",":
				return df
		except Exception:
			pass
	# Fallback to default parser
	return pd.read_csv(io.BytesIO(b))