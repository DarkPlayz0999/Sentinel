"""Real aging datasets (NASA PCoE), prepared for SENTINEL.

    nasa_capacitors.py   Capacitor Electrical Stress (ES10 / ES12 / ES14)
    nasa_mosfet.py       MOSFET Thermal Overstress Aging
    evaluate.py          SENTINEL's methods on the prepared data, scored by src/evaluate.py

The rule these scripts keep: RESHAPE, NEVER RE-MEASURE. Raw files are read and
never written. Every output value is either a measured value copied through, or
a quantity derived from measured values by a formula stated in the data
dictionary. No reading is smoothed, scaled, dropped for being inconvenient, or
invented. Excluded records are listed with the reason.

Outputs go to data/real/ (gitignored like the rest of data/): the raw files are
external and large, so what the repo carries is the recipe, not the result.
"""
