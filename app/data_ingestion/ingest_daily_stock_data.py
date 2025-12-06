# data_ingestion.py
import logging
from datetime import datetime, timedelta
from io import StringIO
from typing import List

import duckdb
import pandas as pd
import requests
import yfinance as yf

# -----------------------------------
# Config & Logging
# -----------------------------------
DUCKDB_PATH = "app/stocks.duckdb"  # adjust path as needed
TRADING_DAYS = 50                  # minimum historical trading days
TOP_N_STOCKS = 100

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


# -----------------------------------
# DuckDB Setup
# -----------------------------------
def init_duckdb(db_path: str) -> duckdb.DuckDBPyConnection:
    """
    Initialize DuckDB connection and ensure required tables exist.
    """
    conn = duckdb.connect(db_path)

    # Stock metadata
    conn.execute("""
    CREATE TABLE IF NOT EXISTS stock_metadata (
        symbol TEXT PRIMARY KEY,
        name   TEXT
    )
    """)

    # Daily stock data
    conn.execute("""
    CREATE TABLE IF NOT EXISTS daily_stock_data (
        trade_date  DATE,
        symbol      TEXT,
        close_price DOUBLE,
        market_cap  DOUBLE,
        PRIMARY KEY (trade_date, symbol)
    )
    """)

    # Index composition table (for API / index logic)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS index_composition (
        trade_date DATE,
        symbol     TEXT,
        weight     DOUBLE,
        PRIMARY KEY (trade_date, symbol)
    )
    """)

    # Index performance table (for API / index logic)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS index_performance (
        trade_date   DATE PRIMARY KEY,
        index_level  DOUBLE,
        daily_return DOUBLE
    )
    """)

    return conn


# -----------------------------------
# Universe Selection
# -----------------------------------
def get_universe_symbols() -> List[str]:
    """
    Get the universe of symbols to ingest – e.g., all S&P 500 tickers.
    We will later pick daily top 100 by market cap at index build time.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        )
    }

    logger.info("Fetching S&P 500 constituents from Wikipedia for universe...")
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    sp500_table = pd.read_html(StringIO(response.text))[0]
    tickers = sp500_table["Symbol"].tolist()
    logger.info(f"Universe size: {len(tickers)} symbols.")
    return tickers



# -----------------------------------
# Fetch Historical Data
# -----------------------------------
def fetch_stock_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch historical prices via yfinance and compute approximate market cap
    as close_price * current sharesOutstanding.

    Note: This approximates historical market cap and should be clearly
    documented in README as a modeling simplification.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info  # single call
        shares_outstanding = info.get("sharesOutstanding")

        if not shares_outstanding:
            logger.warning(f"Shares outstanding missing for {symbol}, skipping.")
            return pd.DataFrame()

        hist = ticker.history(start=start_date, end=end_date)
        if hist.empty:
            logger.warning(f"No historical data for {symbol}")
            return pd.DataFrame()

        hist = hist.reset_index()
        hist["symbol"] = symbol
        hist["market_cap"] = hist["Close"] * shares_outstanding

        # Normalize Date to pure date here
        hist["Date"] = pd.to_datetime(hist["Date"]).dt.date

        hist = hist[["Date", "symbol", "Close", "market_cap"]]
        hist.rename(
            columns={
                "Date": "trade_date",
                "Close": "close_price",
            },
            inplace=True,
        )
        return hist

    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()


# -----------------------------------
# Insert Data into DuckDB
# -----------------------------------
def insert_daily_data(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """
    Append-only insert:
    - Normalize trade_date to pure date (no time component)
    - De-duplicate rows within the incoming DataFrame on (trade_date, symbol)
    - Insert only rows that do NOT already exist in daily_stock_data
      to avoid primary key violations.
    """
    if df.empty:
        return

    # Ensure trade_date is a date (not full datetime) to match DuckDB DATE type
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    # 1) Make sure there are no duplicate (trade_date, symbol) rows in df itself
    df = df.drop_duplicates(subset=["trade_date", "symbol"], keep="last")

    conn.register("temp_daily", df)

    # 2) Insert only rows not already present in daily_stock_data
    conn.execute(
        """
        INSERT INTO daily_stock_data (trade_date, symbol, close_price, market_cap)
        SELECT t.trade_date, t.symbol, t.close_price, t.market_cap
        FROM temp_daily t
        LEFT JOIN daily_stock_data d
          ON d.trade_date = t.trade_date
         AND d.symbol = t.symbol
        WHERE d.trade_date IS NULL
        """
    )

    conn.unregister("temp_daily")



def insert_stock_metadata(conn: duckdb.DuckDBPyConnection, symbol: str, name: str) -> None:
    """
    Insert stock metadata (idempotent).
    """
    try:
        conn.execute(
            """
            INSERT INTO stock_metadata (symbol, name)
            VALUES (?, ?)
            ON CONFLICT(symbol) DO NOTHING
            """,
            [symbol, name],
        )
    except Exception as e:
        logger.error(f"Error inserting metadata for {symbol}: {e}")


# -----------------------------------
# Main Ingestion Job
# -----------------------------------
def run_ingestion() -> None:
    logger.info("Starting data ingestion job...")
    conn = init_duckdb(DUCKDB_PATH)

    # Compute date window (extra calendar days to cover non-trading days/holidays)
    end_date = datetime.today()
    start_date = end_date - timedelta(days=TRADING_DAYS * 2)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # 1. Choose universe
    try:
        symbols = get_universe_symbols()
    except Exception as e:
        logger.error(f"Failed to determine top 100 universe: {e}")
        conn.close()
        return

    # 2. Fetch and insert data for each symbol
    for symbol in symbols:
        logger.info(f"Ingesting data for {symbol}...")
        df = fetch_stock_data(symbol, start_str, end_str)
        if df.empty:
            logger.warning(f"No usable data for {symbol}, skipping ingestion.")
            continue

        # Insert history
        insert_daily_data(conn, df)

        # Insert metadata (shortName fallback to symbol)
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            name = info.get("shortName") or symbol
            insert_stock_metadata(conn, symbol, name)
        except Exception as e:
            logger.warning(f"Could not fetch metadata for {symbol}: {e}")

    logger.info("Data ingestion completed successfully.")
    conn.close()


if __name__ == "__main__":
    run_ingestion()
