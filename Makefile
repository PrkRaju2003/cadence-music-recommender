.PHONY: seed run test evaluate export plans powerbi check
seed:
	python -m cadence.seed
run:
	uvicorn cadence.api:app --host 127.0.0.1 --port 8000 --reload
test:
	python -m pytest -q
evaluate:
	python -m cadence.evaluate
export:
	python -m cadence.export
plans:
	python -m scripts.query_plans
powerbi:
	python scripts/validate_powerbi.py
check: test evaluate export plans
