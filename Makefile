# Same pipeline without Docker (needs uv: https://docs.astral.sh/uv/)
.PHONY: all test analyze verify live
all:
	uv run python -m itb all
test:
	uv run pytest -q tests
analyze:
	uv run python -m itb analyze
verify:
	uv run python -m itb verify
live:  # needs ITB_KEYPAIR=/abs/path/keypair.json (outside the repo)
	uv run python -m itb run --live --yes-spend --minutes 60
	uv run python -m itb collect --skip-done
	uv run python -m itb analyze
