import pandas as pd
d = pd.read_csv("/Users/mac/Documents/GitHub/Study/soosiro_수질TMS/tms_crawling/data/compare_20261106_145634/only_in_A.csv", dtype=str, encoding="utf-8-sig")
print(d.groupby(["연도","분기"]).size())