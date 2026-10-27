SEED ?= 20261022
install:   ; pip install -r requirements.txt
starter:   ; python generate.py --scale starter --seed $(SEED) --out output/starter && python validate.py --data output/starter
full:      ; python generate.py --scale full --seed $(SEED) --out output/full && python validate.py --data output/full
test:      ; python -m pytest -q
repro:     ; python reproduce.py --scale starter --seed $(SEED)
sql:       ; python export_sql.py --data output/starter --db output/starter/supply_chain.db
docs:      ; python schema.py
