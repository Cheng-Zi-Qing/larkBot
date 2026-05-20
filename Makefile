.PHONY: init install start stop restart reload status logs clean test-llm

CTL = ./scripts/ctl.sh

init:
	python3 setup.py

install:
	pip install -r requirements.txt
	@command -v lark-cli >/dev/null 2>&1 || { echo "lark-cli not found. Run: npx @larksuite/cli@latest install"; exit 1; }
	@echo "Dependencies installed."

start:
	@$(CTL) start

stop:
	@$(CTL) stop

restart:
	@$(CTL) restart

reload:
	@$(CTL) restart

status:
	@$(CTL) status

logs:
	@$(CTL) logs

clean:
	rm -rf run/ __pycache__ *.pyc
	@echo "Cleaned."

test-llm:
	python3 test_llm.py
