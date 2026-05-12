.PHONY: infra-up infra-down start stop check compile clean

infra-up:
	docker compose up -d

infra-down:
	docker compose down

start:
	./scripts/start-local.sh

stop:
	./scripts/stop-local.sh

check:
	./scripts/check-local.sh

compile:
	PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q common services

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
	find . -name '.DS_Store' -delete
