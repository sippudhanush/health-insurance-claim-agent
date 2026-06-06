.PHONY: install run-backend run-frontend run docker-up docker-down test test-docs clean

install:
	pip install -r backend/requirements.txt
	pip install streamlit httpx python-dotenv

run-backend:
	uvicorn backend.main:app --reload --port 8000

run-frontend:
	streamlit run frontend/app.py --server.port 8501

run:
	@echo "Start backend and frontend in separate terminals:"
	@echo "  make run-backend"
	@echo "  make run-frontend"

docker-up:
	docker compose up --build

docker-down:
	docker compose down

test:
	python backend/generate_test_reports.py

test-docs:
	python backend/generate_test_docs.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .venv/
