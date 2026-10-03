.PHONY: install backend frontend up down test lint

install:
	python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
	cd frontend && npm ci

backend:
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

up:
	docker compose up --build -d

down:
	docker compose down

lint:
	cd frontend && npm run lint

test:
	cd backend && .venv/bin/python -m pytest tests
