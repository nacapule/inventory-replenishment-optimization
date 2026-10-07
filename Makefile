PYTHON ?= python3
CONFIG ?= configs/published.toml
DATA_URL := https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip
DATA_FILE := data/raw/online_retail_II.xlsx
EXPORTS := exports
CLI := $(PYTHON) src/replenishment.py

.PHONY: data test analyze readme verify all clean

# Download the workbook if it is missing, then check its size and SHA-256.
data: $(DATA_FILE)
	$(CLI) check --config $(CONFIG) --input $(DATA_FILE)

$(DATA_FILE):
	mkdir -p data/raw
	curl -L --fail "$(DATA_URL)" -o data/raw/online-retail-ii.zip
	unzip -o data/raw/online-retail-ii.zip -d data/raw
	rm -f data/raw/online-retail-ii.zip

test:
	$(PYTHON) -m unittest discover -s tests

analyze: $(DATA_FILE)
	$(CLI) analyze --config $(CONFIG) --input $(DATA_FILE) --output $(EXPORTS)

readme:
	$(CLI) readme --output $(EXPORTS)

# Rebuild in a temporary folder and compare with the committed exports.
verify: $(DATA_FILE)
	$(CLI) verify --config $(CONFIG) --input $(DATA_FILE) --output $(EXPORTS)

all: test analyze readme

# Temporary files only; the committed exports are never removed.
clean:
	rm -rf $(EXPORTS).staging $(EXPORTS).previous
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
