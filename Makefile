.PHONY: docs
all: commands

## commands: show available commands (*)
commands:
	@grep -h -E '^##' ${MAKEFILE_LIST} \
	| sed -e 's/## //g' \
	| column -t -s ':'

## check: check code issues
check:
	@ruff check .

## clean: clean up
clean:
	@rm -rf ./dist ./frml.egg-info
	@find . -path './.venv' -prune -o -type d -name '__pycache__' -exec rm -rf {} +
	@find . -path './.venv' -prune -o -type f -name '*~' -exec rm {} +

## coverage: run tests with coverage
coverage:
	@python -m coverage run -m pytest tests
	@python -m coverage report --show-missing

## docs: make documentation
docs:
	@find . -path './.venv' -prune -o -type f -name '*~' -exec rm {} +
	@cp README.md pages/index.md
	@cp CODE_OF_CONDUCT.md pages/conduct.md
	@cp CONTRIBUTING.md pages/contributing.md
	@cp LICENSE.md pages/license.md
	@zensical build --clean
	@touch docs/.nojekyll

## fix: fix code issues
fix:
	@ruff check --fix .

## format: format code
format:
	@ruff format .

## package: build package
package:
	@python -m build

## publish: publish using ~/.pypirc credentials
publish:
	@twine upload --verbose dist/*

## test: run tests
test:
	@pytest tests
