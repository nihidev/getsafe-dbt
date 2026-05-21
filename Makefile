.PHONY: up down build logs agent-logs ui-logs

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

agent-logs:
	docker compose logs -f agent

ui-logs:
	docker compose logs -f chat_ui
