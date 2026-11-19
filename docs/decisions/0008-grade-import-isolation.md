# 8. Serializable isolation for CSV grade imports

Each CSV upload for one assessment runs in a single PostgreSQL
transaction. If any row fails validation, the upload shows the row
errors and saves no grades.

We chose SERIALIZABLE because the import reads enrollment data and then
writes grades. When concurrent transactions commit, the result must be
consistent with some serial order. PostgreSQL can abort an import if it
cannot guarantee that result.

We tested a CSV with one valid row and one invalid score. The upload
reported the invalid row and left the existing grade at 74.80.
A valid CSV then reported that two grades were saved.
