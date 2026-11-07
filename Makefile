.RECIPEPREFIX = >
.PHONY: dev demo test check test-docker install uninstall doctor

dev:
> ./scripts/dev.sh

test:
> tests/run.sh

demo:
> tests/demo.sh

test-docker:
> docker compose -f tests/docker/compose.yml run --rm tests

check:
> python3 -m compileall -q astra
> for f in astra/web/*.js astra/web/ui/*.js; do node --check $$f; done

install:
> sudo ./install.sh

uninstall:
> sudo ./uninstall.sh

doctor:
> ./scripts/doctor.sh
