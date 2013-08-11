.PHONY: upload1

regen: upload1 user_and_index_simple

upload1:
	cd upload1 && python ../../regendoc.py --update upload1.rst

user_and_index_simple:
	python ../regendoc.py --update user_and_index_simple.rst
