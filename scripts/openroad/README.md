# OpenROAD extraction

Real placement and real per-instance power, for `critical_review.md` item 17 —
what power maps actually look like.

```bash
open -a Docker                                    # daemon must be running
docker pull --platform linux/amd64 openroad/orfs:latest

SP=/tmp/orfs && mkdir -p $SP/orfs
# 1. synthesise + place (stops before CTS, see below)
docker run --rm --platform linux/amd64 -v $SP/orfs:/output openroad/orfs:latest bash -lc \
  'source /OpenROAD-flow-scripts/env.sh >/dev/null 2>&1; cd /OpenROAD-flow-scripts/flow &&
   make DESIGN_CONFIG=./designs/asap7/gcd/config.mk results/asap7/gcd/base/3_place.odb &&
   cp -r results /output/'

# 2. extract placement + per-instance power
docker run --rm --platform linux/amd64 -v $SP/orfs:/orfs -v $SP:/output \
  -e PLAT=asap7 -e DES=gcd -e ACTIVITY=0.2 openroad/orfs:latest bash -lc \
  'source /OpenROAD-flow-scripts/env.sh >/dev/null 2>&1;
   openroad -exit -no_init /output/extract_placed_power.tcl'

# 3. analyse
ORFS_EXTRACT_DIR=$SP python physics_accelerated/src/openroad_power.py --design gcd
```

## Two things this environment forced

**CTS crashes under amd64 emulation on Apple silicon** — `illegal instruction`
in TritonCTS, because Rosetta does not implement the instructions it uses. The
flow therefore stops at `3_place`. That is sufficient here: placement is what
sets the spatial power distribution. Routing and clock-tree buffers would add
power and concentrate it further, so every concentration number this produces is
a **lower bound**.

**`sta::instance_power` segfaults** in the same environment. The per-instance
power comes from parsing `report_power -instances`, which works.

Both are environment limits, not flow limits — on an x86 host the full RTL-to-GDS
flow should run and would give routed power instead of placed.
