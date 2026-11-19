# 8. Serializable isolation for CSV grade imports

Each POST to the import page (`grading/views.py`, `grade_import`) runs in one PostgreSQL transaction at SERIALIZABLE.
Rows are checked before anything is written. If any row of any file is wrong, the page lists every error and saves
nothing.

Why SERIALIZABLE: an import reads the enrollments and the existing grades, then writes grades. Under READ COMMITTED
a second import or an enrollment change can commit in between, and both transactions succeed on data the other did
not see. SERIALIZABLE makes PostgreSQL abort one of them with SQLSTATE 40001. The view answers 409 and asks the user
to choose the files again; it does not retry by itself, because the uploaded files are gone after the request.

`SET TRANSACTION ISOLATION LEVEL` must be the first statement of the transaction, so the view cannot run inside
another atomic block. Do not turn on `ATOMIC_REQUESTS`. Tests for the import use `TransactionTestCase` for the same
reason.

Preview and confirm are two requests, so two transactions. The preview puts the parsed scores in a signed token (salt,
user and assessment checked, valid 15 minutes) with the enrollment ids, the max score and a hash of the current grades.
Confirm saves only if all three are unchanged. This also stops the same preview from being confirmed twice.

Tests in `grading/test_grade_import.py` check the isolation level inside the transaction and force a real
serialization failure with a second connection.
