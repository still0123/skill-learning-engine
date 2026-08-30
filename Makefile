PYTHON ?= python3.11

.PHONY: test demo

test:
	$(PYTHON) -m unittest discover -s tests -v

demo:
	$(PYTHON) -m skill_learning demo --workspace ./demo-workspace
