.PHONY: build upload clean
.DEFAULT_GOAL := build

build:
	python setup.py sdist

upload:
	python -m twine upload "dist/${shell ls -v dist/ | tail -n 1}"
	
clean:
	rm -R dist
	
