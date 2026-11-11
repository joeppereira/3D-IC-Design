# Labelled cases for the claim linter
#
# Format: `--- <rule>` begins a case the linter must flag with that rule;
# `--- clean` begins a case it must leave alone. Comment lines start with `#`.
#
# Most of the positives are real retracted claims from this repository's
# history, which is what makes them worth keeping: these are the sentences that
# actually got written, not invented strawmen. The negatives matter more. A
# linter that flags honest prose gets ignored, and the hardest negatives are
# sentences that *quote* a bad claim in order to retract it.

--- percent-accuracy
The surrogate is 95% accurate across the feasible front.

--- percent-accuracy
making its initial guesses 90% accurate without running a solver.

--- vendor-executed
The POD basis is extracted from high-fidelity Ansys Icepak data.

--- vendor-executed
Peak junction temperature confirmed by Celsius at 83.87 °C.

--- signoff-claim
This design is qualified for tape-out at 224 Gbps.

--- unchecked-speedup
The ROI solver is 100,000x faster than the reference.

--- clean
# A ratio with a correctness check in the same breath is accountable.
The direct solve is exact for that mesh and ~300x faster than iterating the FDM
solver to convergence.

--- clean
# Dimensions are not ratios.
16 SERDES_224G_PHY at 600 x 900 um and 16 UCIE2_PHY at 900 x 600 um.

--- clean
# A matrix shape is not a ratio.
The reduced system is 240x240 against 10,240 degrees of freedom.

--- clean
# A lane count is not a ratio.
DRAM Interface: 128x UCIe 2.0 Lanes (8 dies x 16 lanes).

--- clean
# Quoting a bad claim in order to retract it is the opposite of making it.
A ROM advertised as "99.97% accurate" was still 8.71 °C wrong at the peak.

--- clean
# The hedge may land on the next line; a claim is a sentence, not a line.
The finding worth carrying forward: 99.98% "retained energy" is not
99.98% accuracy. Quoting the energy fraction is how a ROM gets
advertised at an accuracy it does not have.

--- clean
# Saying what a licensed run *would* take is not claiming it happened.
Correlating against Icepak would require a 3D assembly and a fluid domain,
which an explorer does not have. No licensed tool has opened these artifacts.

--- clean
# Naming the gate is not claiming sign-off.
The v1 qualification gate had been evaluating a constant rather than the design.

--- clean
# A tier declaration makes the vendor sentence accountable.
Every artifact is emitted and parsed independently (T0); PrimeSim ingestion
would be T1.

--- clean
# Physical units with a basis are the house standard.
Held-out field RMSE is 0.6889 K and mean absolute peak error 1.0812 K.
