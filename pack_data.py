"""data/price data/flow 캐시를 하나의 parquet (data/panel.parquet) 로 묶는다. git 으로 올리기 위한 용도."""
from pathlib import Path

import pandas as pd

from fetch_data import DATA_DIR, load_panel

O, C, I, F = load_panel()
frames = []
for name, df in [("open", O), ("close", C), ("inst", I), ("foreign", F)]:
    s = df.stack(future_stack=True).rename(name)
    frames.append(s)
panel = pd.concat(frames, axis=1).dropna(how="all")
panel.index.names = ["date", "ticker"]
out = DATA_DIR / "panel.parquet"
panel.to_parquet(out, compression="zstd")
print(f"{out} 저장: {len(panel):,} 행 / {out.stat().st_size/1e6:.1f} MB")
