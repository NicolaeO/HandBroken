PYTHON ?= python
FOLDER ?= .

.PHONY: help check preview scan encode run clean revert

help:
	@echo "HandBroken -- batch AV1 transcoder"
	@echo ""
	@echo "Setup"
	@echo "  make check                   Verify ffmpeg, ffprobe, and encoder are ready"
	@echo "  make preview FILE=<path>     Generate quality calibration clips"
	@echo "       preview FILE=<path> START=120 DURATION=15"
	@echo ""
	@echo "Encoding"
	@echo "  make scan   FOLDER=<path>    Scan a folder, write scan JSON to results/"
	@echo "  make encode                  Pick a scan JSON and encode"
	@echo "  make run    FOLDER=<path>    Scan + encode in one step"
	@echo ""
	@echo "Maintenance"
	@echo "  make clean                   Delete .originals/ after verifying encodes"
	@echo "  make revert                  Restore originals from .originals/"
	@echo ""
	@echo "Options (append to any encode/run target)"
	@echo "  KEEP_LARGER=1                Keep encoded file even if larger than source"
	@echo ""
	@echo "Examples"
	@echo "  make scan   FOLDER=\"K:/Media/TV Series/Ozark/Season 1\""
	@echo "  make encode"
	@echo "  make run    FOLDER=\"K:/Media/TV Series/Ozark\" KEEP_LARGER=1"

check:
	$(PYTHON) check_env.py

preview:
	$(PYTHON) run.py preview "$(FILE)" $(if $(START),--start $(START),) $(if $(DURATION),--duration $(DURATION),)

scan:
	$(PYTHON) run.py scan "$(FOLDER)"

encode:
	$(PYTHON) run.py encode $(if $(KEEP_LARGER),--keep-larger,)

run:
	$(PYTHON) run.py run "$(FOLDER)" $(if $(KEEP_LARGER),--keep-larger,)

clean:
	$(PYTHON) run.py clean

revert:
	$(PYTHON) run.py revert
