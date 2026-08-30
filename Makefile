PYTHON ?= python3.11

.PHONY: test demo experiment-demo

test:
	$(PYTHON) -m unittest discover -s tests -v

demo:
	$(PYTHON) -m skill_learning demo --workspace ./demo-workspace

experiment-demo:
	$(PYTHON) -m skill_learning experiment --runtime demo \
		--output ./experiments/normalization-demo \
		--experiment-id normalization-demo \
		--tasks ./examples/normalization/tasks.jsonl \
		--adapter exact \
		--skill-name normalize \
		--skill-file ./examples/normalization/skills/normalize/SKILL.md \
		--iterations 1 --repeats 3 --bootstrap-samples 1000
