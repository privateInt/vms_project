GO ?= go
.PHONY: test vet build configure smoke up down status
test:
	cd src/platform && $(GO) test -p 1 -race ./...
vet:
	cd src/platform && $(GO) vet ./...
build:
	@mkdir -p build
	cd src/platform && $(GO) build -buildvcs=false -o ../../build/camera-api ./camera/cmd/camera-api
	cd src/platform && $(GO) build -buildvcs=false -o ../../build/model-api ./model/cmd/model-api
	cd src/platform && $(GO) build -buildvcs=false -o ../../build/analysis-api ./analysis/cmd/analysis-api
	cd src/platform && $(GO) build -buildvcs=false -o ../../build/operation-api ./operation/cmd/operation-api
configure:
	python3 src/infra/tools/setup_env.py
smoke:
	python3 src/infra/tools/smoke.py --launch --go $(GO)
up:
	docker compose --env-file .env up -d --build
down:
	docker compose --env-file .env down
status:
	docker compose --env-file .env ps
