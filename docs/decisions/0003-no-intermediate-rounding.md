# 3. No rounding until display

The guidelines' Elif example gives PO1 = 85.0. The brief gives 84 for the same data, because LO2 was cut to 82 before
it was used. Scores are stored and computed as `Decimal`/`NUMERIC` and only rounded when shown. The Elif example is a
test.

Status: proposed, team to confirm.
