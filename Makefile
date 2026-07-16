PYTHON ?= python3
DATA_URL := https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip
DATA_FILE := data/raw/online_retail_II.xlsx

.PHONY: data test analyze all clean

data: $(DATA_FILE)

$(DATA_FILE):
	mkdir -p data/raw
	curl -L --fail "$(DATA_URL)" -o data/raw/online-retail-ii.zip
	unzip -o data/raw/online-retail-ii.zip -d data/raw
	rm -f data/raw/online-retail-ii.zip

test:
	$(PYTHON) -m unittest discover -s tests

analyze: $(DATA_FILE)
	$(PYTHON) src/replenishment.py analyze --input $(DATA_FILE) --output exports

all: test analyze

clean:
	rm -f exports/*.csv exports/*.md exports/*.svg exports/*.db

