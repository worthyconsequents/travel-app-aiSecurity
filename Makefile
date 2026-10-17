.PHONY: up down seed test smoke scenarios demo-reset lint
up:
	docker compose up --build -d --wait
down:
	docker compose down
seed:
	docker compose exec api python -m services.seed
lint:
	docker compose exec api ruff check .
	docker compose exec api ruff format --check .
test:
	docker compose exec api pytest -q
	docker compose exec api python scripts/integration.py
	docker compose exec frontend node -e "fetch('http://localhost:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
smoke:
	python3 scripts/smoke.py
scenarios:
	docker compose exec api python -m services.scenarios
demo-reset:
	docker compose exec api python -m services.seed --reset

# Separate project/network/database; no AWS credentials or vendor keys mounted.
AC = PUBLIC_PORT=8081 docker compose -p boring-travel-agentcore -f compose.yaml -f compose.agentcore.yaml
.PHONY: agentcore-up agentcore-down agentcore-test agentcore-plan
agentcore-up:
	$(AC) up --build -d --wait
agentcore-down:
	$(AC) down
agentcore-test:
	$(AC) exec api pytest -q
	$(AC) exec api python scripts/integration.py
	$(AC) exec api python scripts/agentcore_smoke.py
agentcore-plan:
	$(AC) run --rm --no-deps api python scripts/agentcore_plan.py
.PHONY: agentcore-package
agentcore-package:
	python3 scripts/package_agentcore.py

.PHONY: chat-test agentcore-chat-test
chat-test:
	docker compose exec -T api pytest -q tests/unit/test_travel_assistant.py
	python3 scripts/chat_smoke.py
agentcore-chat-test:
	$(AC) exec -T api pytest -q tests/unit/test_travel_assistant.py
	CHAT_BASE_URL=http://localhost:8081 python3 scripts/chat_smoke.py

.PHONY: monitor-test agentcore-monitor-test monitor-secret-plan
monitor-test:
	docker compose exec -T api pytest -q tests/unit/test_monitor.py
	python3 scripts/monitoring_smoke.py
agentcore-monitor-test:
	$(AC) exec -T api pytest -q tests/unit/test_monitor.py
	MONITOR_BASE_URL=http://localhost:8081 python3 scripts/monitoring_smoke.py
monitor-secret-plan:
	python3 scripts/deploy_monitor_secret.py
