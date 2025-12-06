# app/index_logic.py
from datetime import date
from typing import Optional, List, Dict, Any

import duckdb
import pandas as pd

from .db import get_connection

TOP_N = 100
BASE_INDEX_LEVEL = 100.0


def build_index(start_date: date, end_date: Optional[date] = None) -> Dict[str, Any]:
    """Build index between start_date and end_date (inclusive)."""
    conn = get_connection()

    # If end_date is None, use max available trade_date
    if end_date is None:
        end_date = conn.execute(
            "SELECT MAX(trade_date) FROM daily_stock_data"
        ).fetchone()[0]
        if end_date is None:
            raise ValueError("No data in daily_stock_data")

    # 1. Build / rebuild compositions for date range
    # First, delete any existing compositions & perf in the range to make this idempotent
    conn.execute(
        "DELETE FROM index_composition WHERE trade_date BETWEEN ? AND ?",
        [start_date, end_date],
    )
    conn.execute(
        "DELETE FROM index_performance WHERE trade_date BETWEEN ? AND ?",
        [start_date, end_date],
    )

    # Insert top 100 by market cap per day
    conn.execute(
        """
        WITH ranked AS (
            SELECT
                trade_date,
                symbol,
                close_price,
                market_cap,
                ROW_NUMBER() OVER (
                    PARTITION BY trade_date
                    ORDER BY market_cap DESC
                ) AS rn
            FROM daily_stock_data
            WHERE trade_date BETWEEN ? AND ?
        ),
        top_stocks AS (
            SELECT trade_date, symbol
            FROM ranked
            WHERE rn <= ?
        )
        INSERT INTO index_composition (trade_date, symbol, weight)
        SELECT
            trade_date,
            symbol,
            1.0 / ?
        FROM top_stocks
        """,
        [start_date, end_date, TOP_N, TOP_N],
    )

    # 2. Compute daily index returns, using equal-weighted stock returns
    #    r_i,t = close_t / close_{t-1} - 1
    df_returns: pd.DataFrame = conn.execute(
        """
        WITH comp AS (
            SELECT c.trade_date, c.symbol
            FROM index_composition c
            WHERE c.trade_date BETWEEN ? AND ?
        ),
        prices AS (
            SELECT
                d.trade_date,
                d.symbol,
                d.close_price
            FROM daily_stock_data d
            JOIN comp
            ON d.trade_date = comp.trade_date
            AND d.symbol = comp.symbol
        ),
        lagged AS (
            SELECT
                trade_date,
                symbol,
                close_price,
                LAG(close_price) OVER (
                    PARTITION BY symbol
                    ORDER BY trade_date
                ) AS prev_close
            FROM prices
        ),
        stock_returns AS (
            SELECT
                trade_date,
                symbol,
                CASE
                    WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
                    ELSE (close_price / prev_close) - 1.0
                END AS stock_return
            FROM lagged
        )
        SELECT
            trade_date,
            AVG(stock_return) AS daily_return
        FROM stock_returns
        WHERE stock_return IS NOT NULL
        GROUP BY trade_date
        ORDER BY trade_date
        """,
        [start_date, end_date],
    ).fetch_df()

    if df_returns.empty:
        conn.close()
        raise ValueError("No returns computed for the given date range.")

    # Compute index level with base 100
    df_returns = df_returns.sort_values("trade_date")
    df_returns["index_level"] = BASE_INDEX_LEVEL * (1.0 + df_returns["daily_return"]).cumprod()

    # Insert into index_performance
    conn.register("temp_perf", df_returns[["trade_date", "index_level", "daily_return"]])
    conn.execute(
        """
        INSERT INTO index_performance (trade_date, index_level, daily_return)
        SELECT trade_date, index_level, daily_return FROM temp_perf
        """
    )

    conn.close()
    return {
        "start_date": str(df_returns["trade_date"].min().date()),
        "end_date": str(df_returns["trade_date"].max().date()),
        "num_days": int(df_returns.shape[0]),
    }


def get_index_performance(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    conn = get_connection()
    df = conn.execute(
        """
        SELECT trade_date, index_level, daily_return
        FROM index_performance
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """,
        [start_date, end_date],
    ).fetch_df()
    conn.close()

    if df.empty:
        return []

    base_level = df["index_level"].iloc[0]
    df["cumulative_return"] = df["index_level"] / base_level - 1.0

    records = []
    for row in df.itertuples(index=False):
        records.append(
            {
                "trade_date": str(row.trade_date.date()),
                "index_level": row.index_level,
                "daily_return": row.daily_return,
                "cumulative_return": row.cumulative_return,
            }
        )
    return records


def get_index_composition(date_: date) -> List[Dict[str, Any]]:
    conn = get_connection()
    df = conn.execute(
        """
        SELECT
            c.trade_date,
            c.symbol,
            c.weight,
            m.name,
            d.market_cap
        FROM index_composition c
        LEFT JOIN stock_metadata m ON c.symbol = m.symbol
        LEFT JOIN daily_stock_data d
            ON c.trade_date = d.trade_date
            AND c.symbol = d.symbol
        WHERE c.trade_date = ?
        ORDER BY c.symbol
        """,
        [date_],
    ).fetch_df()
    conn.close()

    return [
        {
            "trade_date": str(row.trade_date.date()),
            "symbol": row.symbol,
            "name": row.name,
            "weight": row.weight,
            "market_cap": row.market_cap,
        }
        for row in df.itertuples(index=False)
    ]


def get_composition_changes(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Returns: list of objects with:
        date, entered: [symbols], exited: [symbols]
    """
    conn = get_connection()
    df = conn.execute(
        """
        SELECT trade_date, symbol
        FROM index_composition
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date, symbol
        """,
        [start_date, end_date],
    ).fetch_df()
    conn.close()

    if df.empty:
        return []

    changes = []
    grouped = {d: sorted(g["symbol"].tolist()) for d, g in df.groupby("trade_date")}
    dates_sorted = sorted(grouped.keys())

    prev_set = None
    for d in dates_sorted:
        current_set = set(grouped[d])
        if prev_set is None:
            prev_set = current_set
            continue

        entered = sorted(list(current_set - prev_set))
        exited = sorted(list(prev_set - current_set))
        if entered or exited:
            changes.append(
                {
                    "trade_date": str(d.date()),
                    "entered": entered,
                    "exited": exited,
                }
            )

        prev_set = current_set

    return changes
