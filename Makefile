.PHONY: build up down logs shell test import generate doctor api-test batch

COMPOSE=docker compose
RUN=$(COMPOSE) run --rm api

build:        ## build the api image
	$(COMPOSE) build api
up:           ## start db + api (http://localhost:8000/docs)
	$(COMPOSE) up -d
down:
	$(COMPOSE) down
logs:
	$(COMPOSE) logs -f api
shell:
	$(RUN) bash
test:         ## run the test-suite inside the container (ffmpeg+libass available)
	$(RUN) pytest -q -p no:warnings
doctor:
	$(RUN) ttcf doctor
import:       ## import/refresh B-roll metadata from ./assets
	$(RUN) ttcf assets import
generate:     ## make TEMPLATE=story_v1 TOPIC="Stop taking meeting notes manually" generate
	$(RUN) ttcf generate --template $(TEMPLATE) --topic "$(TOPIC)"
batch:        ## run the 30-video validation batch
	$(RUN) ttcf batch /app/configs/batch_30.json
