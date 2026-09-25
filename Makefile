.PHONY: prove measure test clean

prove:
	cd prover && go run . ..

measure:
	forge test -vv --match-test test_MeasureVerifyGas

test:
	forge test -vv

clean:
	rm -rf out cache

# Active campaign matrix: soispoke v2 at 235,800, synthetic controls at
# 250k, 300k, 400k and 500k. The 100k point uses the non-Groth16 workloads.
.PHONY: sweep synthetic-sweeps
sweep:
	python3 scripts/synthetic-sweep.py --target $(TARGET) --label $(or $(LABEL),$(TARGET)) --output $(or $(OUTPUT),artifacts) $(if $(ALLOW_DIRTY),--allow-dirty)

synthetic-sweeps:
	$(MAKE) sweep TARGET=250000 LABEL=250k
	$(MAKE) sweep TARGET=300000 LABEL=300k
	$(MAKE) sweep TARGET=400000 LABEL=400k
	$(MAKE) sweep TARGET=500000 LABEL=500k
