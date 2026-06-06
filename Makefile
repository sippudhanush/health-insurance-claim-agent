.PHONY: up down build logs format lint test clean

# Docker commands
up:
	docker compose up --build

upd:
	docker compose up --build -d

logs:
	docker compose logs -f

# Formatting (backend Python)
format:
	ruff format backend/
	ruff check --fix backend/

# Linting
lint:
	ruff check backend/
	ruff format --check backend/

# Tests
test:
	docker compose exec backend python -m pytest tests/ -v

test-local:
	cd backend && python -m pytest tests/ -v

# Cleanup
clean:
	docker compose down -v
	docker system prune -f

# Generate mock documents
mock-docs:
	cd backend && python -m services.mock_doc_generator

# Full rebuild and run
rebuild:
	docker compose down
	docker compose build --no-cache
	docker compose up
