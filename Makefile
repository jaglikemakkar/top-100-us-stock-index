# ============
#  VARIABLES
# ============

PYTHON=python3
UVICORN=uvicorn
APP=app.main:app

# ============
#  TARGETS
# ============

# Create virtual environment and install dependencies
setup:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate; pip install --upgrade pip
	. .venv/bin/activate; pip install -r requirements.txt

# Run ingestion job
ingest:
	$(PYTHON) app/data_ingestion/ingest_daily_stock_data.py

# Validate ingested data
validate:
	$(PYTHON) app/data_ingestion/validate_ingestion.py

# Run FastAPI server locally
run:
	$(UVICORN) $(APP) --reload --host 0.0.0.0 --port 8000

# Run Redis locally (optional helper)
redis:
	docker run -d --name redis-local -p 6379:6379 redis:7 || true

# Stop local Redis
redis-stop:
	docker stop redis-local || true
	docker rm redis-local || true

# Start docker-compose environment
docker-up:
	docker-compose up --build

# Stop docker-compose environment
docker-down:
	docker-compose down

# Remove Docker containers/images (clean rebuild)
docker-clean:
	docker-compose down --rmi all --volumes --remove-orphans

# Clean Python cache files
clean:
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
