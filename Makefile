.PHONY: check

PY ?= python3

# Single check command (kiln and CI run it): byte-compiles the Python sources
# and runs the unit tests. Tests that need a Lean toolchain skip themselves
# when `elan` is not available.
check:
	@set -e; \
	dirs=$$(ls -d lazarillo tests scripts 2>/dev/null || true); \
	if [ -n "$$dirs" ]; then $(PY) -m compileall -q $$dirs; fi; \
	if ls tests/test_*.py >/dev/null 2>&1; then \
		$(PY) -m unittest discover -s tests -p 'test_*.py'; \
	else \
		echo "check: no tests yet"; \
	fi
