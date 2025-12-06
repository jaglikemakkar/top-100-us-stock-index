# validate_ingestion.py
import duckdb
import pandas as pd

DUCKDB_PATH = "app/stocks.duckdb"  # keep consistent with data_ingestion.py


def main():
    con = duckdb.connect(DUCKDB_PATH)

    print("=== Tables in DuckDB ===")
    print(con.execute("SHOW TABLES").fetch_df())
    print()

    print("=== Row counts ===")
    print("daily_stock_data:", con.execute("SELECT COUNT(*) AS cnt FROM daily_stock_data").fetch_df())
    print("stock_metadata:", con.execute("SELECT COUNT(*) AS cnt FROM stock_metadata").fetch_df())
    print("index_composition:", con.execute("SELECT COUNT(*) AS cnt FROM index_composition").fetch_df())
    print("index_performance:", con.execute("SELECT COUNT(*) AS cnt FROM index_performance").fetch_df())
    print()

    print("=== Sample daily_stock_data ===")
    print(con.execute("""
        SELECT *
        FROM daily_stock_data
        ORDER BY trade_date DESC, symbol
        LIMIT 10
    """).fetch_df())
    print()

    print("=== Date range in daily_stock_data ===")
    print(con.execute("""
        SELECT MIN(trade_date) AS min_date,
               MAX(trade_date) AS max_date,
               COUNT(DISTINCT trade_date) AS num_trading_days
        FROM daily_stock_data
    """).fetch_df())
    print()

    print("=== Sample stock_metadata ===")
    print(con.execute("""
        SELECT *
        FROM stock_metadata
        ORDER BY symbol
        LIMIT 10
    """).fetch_df())
    print()

    con.close()


if __name__ == "__main__":
    main()
