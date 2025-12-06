# app/export.py
from datetime import date
from io import BytesIO
from typing import List, Dict, Any

import pandas as pd

from .index_logic import (
    get_index_performance,
    get_index_composition,
    get_composition_changes,
)


def export_to_excel(
    start_date: date, end_date: date
) -> BytesIO:
    perf = get_index_performance(start_date, end_date)
    comps = []
    for d in sorted({p["trade_date"] for p in perf}):
        comps.extend(get_index_composition(date.fromisoformat(d)))
    changes = get_composition_changes(start_date, end_date)

    # Create dataframes
    df_perf = pd.DataFrame(perf)
    df_comps = pd.DataFrame(comps)
    df_changes = pd.DataFrame(changes)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        if not df_perf.empty:
            df_perf.to_excel(writer, sheet_name="IndexPerformance", index=False)
        if not df_comps.empty:
            df_comps.to_excel(writer, sheet_name="DailyComposition", index=False)
        if not df_changes.empty:
            df_changes.to_excel(writer, sheet_name="CompositionChanges", index=False)

        # Optional: format numeric columns, dates, etc.

    buffer.seek(0)
    return buffer
