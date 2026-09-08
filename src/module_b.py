"""Module B - drift forecasting from the first 24 hours.

Predicts Value_168h using ONLY Value_0h and Value_24h, then converts the
predicted slope into an early-reject decision at hour 24 - freeing 144 oven
hours per rejected part.

Three stacked pieces (blueprint section 8):

    1. physics baseline   X(t) = X0 * (1 + A * (t/168)^n)
                          One global exponent n* fitted per parameter; the
                          amplitude A solved per part from the single delta
                          available. Two points cannot fit two parameters per
                          part - fit the shape globally, the magnitude locally.
                          n is also a quantity you can plot and defend: healthy
                          parts settle (n < 1), defects accelerate (n > 1).
    2. learned residual   gradient-boosted regressor given the physics forecast
                          as an input feature, plus lot-relative robust z's and
                          lot-level aggregates.
    3. quantile bound     a second regressor at alpha=0.90. The point estimate
                          is what MAE is reported on; the REJECT decision is
                          made on the upper bound, so a part is rejected when
                          even its optimistic forecast breaches the safety
                          slope. This buys conservatism without costing MAE.

Safety slope = min(mission-based, population-based). Either is grounds for
rejection: (a) says this part will not survive, (b) says this part is not like
its siblings.

    S_mission    = (USL - V_0) / (mission_hours / AF)
                   AF = exp((Ea/k) * (1/T_use - 1/T_stress))
                   Ea ~ 0.7 eV, k = 8.617e-5 eV/K, T in kelvin.
                   At 25 C use / 125 C stress this gives AF ~ 937, so 168
                   burn-in hours is roughly 18 years of field life.
    S_population = median(slope_lot) + 4.5 * 1.4826 * MAD(slope_lot)

TODO: implement. Validation splits are GroupKFold(groups=lot).
"""
