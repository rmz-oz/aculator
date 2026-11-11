# 7. Roles as groups, one department

Three Django groups, created by migration 0002: Student, Instructor, Head of department. Instructors are linked to
offerings, not courses (`CourseOffering.instructors`), because who teaches a course changes between terms. The rules
are in `grading/access.py`; views ask it instead of filtering on their own.

There is no Department model. The POs belong to one program, so "head sees the department" means the head sees
everything. If a second department comes in, Course gets a department FK and `access.py` filters on it.

Status: proposed, team to confirm.
