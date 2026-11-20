# Demo scenarios

The demo database looks like a real department, mistakes included (#100). `python manage.py demo_data` loads it:
`fake_data` (400 students, 8 courses, 8 terms, every grade plausible) and then the scenarios below, from
`grading/demo_scenarios.py`. The same seed gives the same students and the same mistakes every time.
`demo_data --clean` leaves the scenarios out; the tests use the clean data.

With `DEMO=1` (docker compose, the Render demo) this runs on an empty database, and the sign in page offers three
accounts: Student1 Demo (student), Deniz Demo (instructor of CSE203 and CSE301) and Selin Demo (head of department).

## In the data

What a department's database holds after a few years. "Today" is what aculator does with it.

| Scenario | Where | Today |
|---|---|---|
| Typing mistakes, digits swapped or a decimal point slipped | 12 grades, e.g. Student145 CSE102 2025 Spring Project 83.40 as 38.40, Student390 CSE303 2024 Fall Final 74.50 as 7.45 | Accepted: both are between 0 and the maximum. The student's LO drops by 20 points or more |
| Wrong scale: out of 20 typed into an assessment out of 100 | CSE202 2024 Spring, Project, 50 students | Accepted. Class averages 36.4, 40.9 and 70.2 for the three LOs, against 65 to 70 in every other term |
| Wrong assessment: the Midterm list imported as the Final | CSE102 2025 Fall, 43 students | Accepted. Final equals Midterm for every student |
| Score column sorted on its own in Excel | CSE201 2024 Fall, Midterm | Accepted. Every score belongs to another student, the class mean does not change |
| Absent student typed as 0 | 34 Finals, e.g. Student251 CSE202 2025 Spring | Saved as a graded 0. Same number as absent, but the status is lost |
| Absent student marked properly | 35 Finals, e.g. Student215 CSE203 2023 Spring | Counts as 0 (#72) |
| Final row missing, a forgotten page | 8 enrollments, e.g. Student388 CSE302 2025 Fall | The Final is left out of that student's LOs, which can look better than with a 0 |
| Left after the midterm | 54 enrollments with only a Midterm, e.g. Student220 CSE203 2026 Spring | "1 grade" where an LO uses the Midterm, hatched where none does; kept out of class averages (#42) |
| Term in progress | 2026 Fall, only the Midterm entered | Student cells show "1 grade" and class averages stay empty. In CSE101 no LO uses the Midterm, so the whole class is hatched |
| Grade inflation | CSE203 2025 Spring, every grade 18% higher | Shown as is: class averages around 80 against 66 to 73 in other terms |
| Two groups in one class | CSE202 2025 Fall, half around 40, half around 75 | Class average about 50, although almost no student is near 50; only the student rows show the two groups |
| No learning outcomes yet | CSE303 2026 Spring | Grades but no scores. The report says why |
| LO without PO mapping | CSE301 2025 Spring, LO3 | LO3 has scores and feeds no PO |
| A PO no course measures | PO11 | No evidence for any student |
| 3 student elective | CSE491 Selected Topics in Machine Learning, 2025 Spring | One student moves the class mean by a third; no warning |
| 200 student first year course | CSE101 2025 Fall, 34 students plus 166 first years with only this course | First years have one course, most POs without evidence |
| Summer school | CSE102 2024 Summer (6 students), CSE201 2025 Summer (8) | Shown like any term |
| Transfer students | Transfer567 to Transfer581, 1 to 3 courses each | Profile mostly without evidence |
| Erasmus students | Erasmus582 to Erasmus586, CSE302 and CSE303 in 2025 Spring | Counted in the department means |
| Instructors | Every course has one; CSE302 changes from Elif Şahin to Burak Çelik in 2025 | Both stay listed: the one who left still sees the grades (decision 7 has no dates) |

The first four are the point of the demo: plausible wrong numbers pass every check the import has, and only someone
who looks at the class report notices. A check for scores far from the student's other work, or a whole column
under 25% of the maximum, would catch them.

## Import files

`docs/demo_files/` holds files that instructors and Excel really produce. Use them on CSE301 2026 Fall as Deniz Demo:
its Final is not entered yet. Every message below is what the app shows today.

| File | Use on | The app says |
|---|---|---|
| `01_final_ok_two_missing.csv` | Final, Preview | "29 grades will be saved"; the two students not in the file can be marked absent. Semicolons and decimal comma work |
| `02_out_of_range.csv` | Final | "Score must be between 0 and 100.00" for 850 and 105. Nothing saved |
| `03_absence_codes.csv` | Final | "Score must be a number" for G, GR, DZ and -. Absence is marked in the preview instead |
| `04_excel_trailing_columns.csv` | Final | "The first row must be student_number,score": right, but it does not say the empty columns are the cause (#106) |
| `05_optical_reader.csv` | Final | The same message for a tab separated `Öğrenci No`, `Not` export (#106, #96) |
| `06_windows_1254.csv` | Final | "File is not UTF-8. Save it as CSV UTF-8" |
| `07_xlsx_renamed.csv` | Final | The same UTF-8 message, although the file is a spreadsheet (#106) |
| `08_decimal_comma_in_comma_file.csv` | Final | "Score must be a number" on every row; nothing hints at the decimal comma (#106) |
| `09_formula_decimals.csv` | Final | "Score can have at most two decimal places" |
| `10_duplicate_student_a.csv` and `_b.csv` together | Final | "appears again, first at 10_duplicate_student_a.csv, line 18" for the overlap |
| `11_final_list_for_midterm.csv` | Midterm, Preview | "31 grades will be saved, 30 of them replacing an existing grade", with every change listed. Import without preview would overwrite silently |

Two more to show by hand:

- Preview a file, change one of its grades in the admin, then confirm: "Grades for this assessment changed after the
  preview". Nothing is saved.
- Lower an assessment's maximum below a grade it has, in the admin: refused (#101).

## Fixed while preparing this

- #101 A maximum below an existing score is refused; before, scores went above 100%.
- #102 If refreshing the score views fails after the grades are saved, the error is logged and the page still says what
  was saved; before, the instructor got a server error for saved grades.
- #103 The import form sends once, and a second request that finds the same grades already stored says so instead of
  "nothing was saved".

## Not in the data yet

These would show wrong numbers today, so they wait for the model:

- Retaking a failed course: both attempts count (#104).
- Makeup exam replacing the final (#105).
- ECTS changed between years: it rewrites old terms (#80).
- Grade changed after an appeal: no history (#35).
