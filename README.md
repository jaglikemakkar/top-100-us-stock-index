# Equal-Weighted Top 100 US Stock Index

This project implements a backend service that tracks and manages a **custom equal-weighted stock index** comprising the **top 100 US stocks by daily market capitalization**.

For each trading day:

- The universe is the **S&P 500**.
- The system selects the **top 100 stocks by market cap** from that universe.
- It constructs an **equal-weighted index**, rebalanced daily.
- It exposes APIs to:
  - Build the index over arbitrary date ranges.
  - Retrieve performance and composition.
  - Detect composition changes (entries/exits).
  - Export results to Excel.

---

## High-Level Architecture

**Components:**

- **Data ingestion (standalone job)**  
  - `app/data_ingestion/ingest_daily_stock_data.py`
  - Fetches historical daily price data via **yfinance** for all S&P 500 tickers.
  - Approximates daily market cap as `Close * sharesOutstanding`.
  - Stores into **DuckDB** in `app/stocks.duckdb`.

- **Backend API (FastAPI)**  
  - `app/main.py`, `app/api.py`, `app/index_logic.py`, `app/export.py`
  - Implements REST endpoints for index construction, retrieval, and export.

- **Database (DuckDB)**  
  - Single file DB: `app/stocks.duckdb`.

- **Caching (Redis)**  
  - Caches responses for:
    - `/index-performance`
    - `/index-composition`
    - `/composition-changes`

- **Containerization**
  - `Dockerfile`
  - `docker-compose.yml` spins up:
    - API service
    - Redis

---

## Data Model (DuckDB Schema)

The ingestion script creates and uses the following tables:

### `stock_metadata`

| Column | Type | Description               |
|--------|------|---------------------------|
| symbol | TEXT | Ticker symbol (PK)        |
| name   | TEXT | Company short name        |

### `daily_stock_data`

| Column     | Type  | Description                              |
|------------|-------|------------------------------------------|
| trade_date | DATE  | Trading date (PK part 1)                 |
| symbol     | TEXT  | Ticker symbol (PK part 2)                |
| close_price| DOUBLE| Daily close price                        |
| market_cap | DOUBLE| Approximate daily market cap             |

**Primary key:** `(trade_date, symbol)`

> Daily market cap is approximated as `close_price * current sharesOutstanding` from yfinance. This is a modeling simplification and is documented as such.

### `index_composition`

| Column     | Type  | Description                               |
|-----------|-------|-------------------------------------------|
| trade_date| DATE  | Date of index composition (PK part 1)     |
| symbol    | TEXT  | Constituent symbol (PK part 2)            |
| weight    | DOUBLE| Equal weight (typically 1/100)            |

### `index_performance`

| Column      | Type  | Description                               |
|-------------|-------|-------------------------------------------|
| trade_date  | DATE  | Date (PK)                                 |
| index_level | DOUBLE| Index level (base 100)                    |
| daily_return| DOUBLE| Daily index return                        |

> `index_level` is computed from daily returns as a cumulative product with a base of 100.

---

## Index Methodology

- **Universe:** S&P 500 constituents (scraped from Wikipedia).
- **Selection:** For each day in the requested range:
  - Rank all available stocks by `market_cap` (from `daily_stock_data`).
  - Select the **top 100**.
- **Weighting:** Assign **equal notional weights** of `1/100` to each of the 100 stocks.
- **Rebalancing:**  
  - The index is modeled as being **rebalanced daily**.
  - Daily index return is computed as the **simple average** of the selected stocks’ daily returns.
- **Index Level:**  
  - Base value of **100** on the first day in the range.
  - Subsequent levels are computed via cumulative product of `(1 + daily_return)`.

---

## Local Setup

### 1. Python Environment

```bash
# From project root
python -m venv .venv
source .venv/bin/activate  # on macOS/Linux
# .venv\Scripts\activate   # on Windows

pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Run Data Ingestion Job
The ingestion job must be run before building the index.
```bash
python app/data_ingestion/ingest_daily_stock_data.py
```
This will:
- Fetch S&P500 symbols from Wikipedia.
- Download historical daily prices via yfinance.
- Compute approximate daily market cap.
- Insert into app/stocks.duckdb

You can validate the ingested data with an optional script (if present):

```bash
python app/data_ingestion/validate_ingestion.py
```

### 3. Run Redis (for caching)
For local development, the easiest way is via Docker:
```bash
docker run -d --name redis-local -p 6379:6379 redis:7
```
The FastAPI app expects Redis at localhost:6379 when run locally.
Make sure `redis_host` in `config.py` is set to `"localhost"`

### 4. Start FastAPI Server
From the project root:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Now you can visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Docker Setup
### 1. Build & Run with docker-compose
Make sure you have Dockerfile and docker-compose.yml in the project root.

Example `docker-compose` usage:

```bash
docker-compose up --build
```

This will:
- Build the API container.
- Start the API on port 8000.
- Start Redis on port 6379.

When running inside Docker:
- `REDIS_HOST` is set to `redis` (the service name).
- DuckDB file is mounted as a volume (e.g., ./app/stocks.duckdb).

