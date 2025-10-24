import pandas as pd
from src.genai_copilot.anomalies import detect_anomalies


def test_detect_anomalies_runs():
df = pd.DataFrame({"revenue": [100, 150, 155, 400]})
rep = detect_anomalies(df)
assert "outliers" in rep and isinstance(rep["outliers"], dict)