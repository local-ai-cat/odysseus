# Odysseus developer tasks. Mirrors the confnote/conferences pattern.
.DEFAULT_GOAL := help
.PHONY: help test app-prod app-dev app-install app-release
DEV_TAG ?= local

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run the unit test suite (in the repo venv)
	venv/bin/python -m pytest -q

app-prod: ## Build/sign self-contained "Odysseus.app" (trimmed: no tests/kubernetes)
	packaging/build-macos.sh

app-dev: ## Build/sign "Odysseus dev.app" (full: bundles tests + kubernetes; DEV_TAG=local)
	ODYSSEUS_DEV_TAG=$(DEV_TAG) packaging/build-macos.sh dev $(DEV_TAG)

app-install: app-prod app-dev ## Build both prod and dev apps side by side

app-release: ## Build/sign/notarize the trimmed prod app for distribution
	NOTARIZE=1 packaging/build-macos.sh
