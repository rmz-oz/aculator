# Sprints

Velocity and short meeting notes, one section per sprint. Points come from the `points:` labels on issues
(planning poker). `main` is tagged `sprint-N` when the sprint closes.

Board: [GitHub Projects](https://github.com/users/rmz-oz/projects/1), set up by Ramiz, run by Rana as product owner.

## Sprint 1 (2026-10-29 to 2026-11-05): Skeleton, models, diagrams

| | points |
|---|---|
| Planned | 22 |
| Done | 20 |

| # | Issue | Assignee | Points | Status |
|---|---|---|---|---|
| [#1](https://github.com/rmz-oz/aculator/issues/1) | Django project skeleton on PostgreSQL | rmz-oz | none | done before points were set, PR [#23](https://github.com/rmz-oz/aculator/pull/23) |
| [#2](https://github.com/rmz-oz/aculator/issues/2) | Core models | esinsarialtin | 5 | done, PR [#26](https://github.com/rmz-oz/aculator/pull/26) |
| [#3](https://github.com/rmz-oz/aculator/issues/3) | ER diagram | sarginyaren | 2 | done, PR [#64](https://github.com/rmz-oz/aculator/pull/64) |
| [#4](https://github.com/rmz-oz/aculator/issues/4) | Architecture diagram | rmz-oz | 2 | done, PR [#24](https://github.com/rmz-oz/aculator/pull/24) |
| [#5](https://github.com/rmz-oz/aculator/issues/5) | Fake data command | sarginyaren | 5 | done, PR [#66](https://github.com/rmz-oz/aculator/pull/66) |
| [#6](https://github.com/rmz-oz/aculator/issues/6) | Project board and sprint routine | ranayilmazz | 2 | moved to Sprint 2 |
| [#7](https://github.com/rmz-oz/aculator/issues/7) | Screen sketches | ranayilmazz | 2 | done, PR [#63](https://github.com/rmz-oz/aculator/pull/63) |
| [#27](https://github.com/rmz-oz/aculator/issues/27) | CI passes with zero tests | rmz-oz | 1 | done, PR [#28](https://github.com/rmz-oz/aculator/pull/28) |
| [#29](https://github.com/rmz-oz/aculator/issues/29) | Deploy main to Render | rmz-oz | 3 | done, PR [#30](https://github.com/rmz-oz/aculator/pull/30) |

Extra work, no points: decision notes on outcome weights ([#62](https://github.com/rmz-oz/aculator/pull/62)) and visual language ([#58](https://github.com/rmz-oz/aculator/pull/58)), deploy waits for the new commit to be live ([#61](https://github.com/rmz-oz/aculator/pull/61)).

`main` tagged `sprint-1` at 3464d73.

### Planning (2026-10-29)

- One week sprints, Thursday to Thursday. Milestones Sprint 1 to Sprint 3 opened first, later extended to Sprint 8 (Dec 24).
- Roles: Ramiz architecture and team lead, Yaren data (ER diagram, fake data), Esin backend and calculation, Rana product owner and UI.
- Sprint 1 goal: Django on PostgreSQL, core models, ER and architecture diagrams, fake data, screen sketches, board.
- Weight between courses is ECTS, editable per course. LO to PO weights are integers 1 to 5.

### Review (2026-11-05)

- 20 of 22 points done. Only #6 left, moved to Sprint 2.
- Every PR needs one approval. The first week showed that a comment saying "looks good" is not an approval, so reviews took longer than the code. From now on use the Approve button.
- App runs on Render from `main`. Deploy now waits until the new commit is live.
- Fake data is reproducible with `--seed`, covers 11 POs and is tested (18 tests).
- Carry over to Sprint 2: #6, class diagram PR #65, Getting Real notes PR #59.

## Sprint 2 (2026-11-05 to 2026-11-12): Calculation, views, mid semester presentation

| | points |
|---|---|
| Planned | 34 |
| Done | 34 |

| # | Issue | Assignee | Points | Status |
|---|---|---|---|---|
| [#6](https://github.com/rmz-oz/aculator/issues/6) | Project board and sprint routine | ranayilmazz | 2 | done, PR [#76](https://github.com/rmz-oz/aculator/pull/76) |
| [#8](https://github.com/rmz-oz/aculator/issues/8) | LO and PO calculation | esinsarialtin | 5 | done, PR [#71](https://github.com/rmz-oz/aculator/pull/71) |
| [#9](https://github.com/rmz-oz/aculator/issues/9) | Materialized views for student profiles | sarginyaren | 8 | done, PR [#74](https://github.com/rmz-oz/aculator/pull/74) |
| [#10](https://github.com/rmz-oz/aculator/issues/10) | Roles and permissions | rmz-oz | 5 | done, PR [#68](https://github.com/rmz-oz/aculator/pull/68) |
| [#11](https://github.com/rmz-oz/aculator/issues/11) | Course report page | ranayilmazz | 5 | done, PR [#75](https://github.com/rmz-oz/aculator/pull/75) |
| [#12](https://github.com/rmz-oz/aculator/issues/12) | CSE 321 checkpoint presentation and report | rmz-oz | 3 | done, PR [#73](https://github.com/rmz-oz/aculator/pull/73) |
| [#25](https://github.com/rmz-oz/aculator/issues/25) | PO components | esinsarialtin | 3 | done, PR [#78](https://github.com/rmz-oz/aculator/pull/78) |
| [#31](https://github.com/rmz-oz/aculator/issues/31) | Class diagram | rmz-oz | 1 | done, PR [#65](https://github.com/rmz-oz/aculator/pull/65) |
| [#34](https://github.com/rmz-oz/aculator/issues/34) | Getting Real notes | rmz-oz | 1 | done, PR [#59](https://github.com/rmz-oz/aculator/pull/59) |
| [#60](https://github.com/rmz-oz/aculator/issues/60) | Deploy check can pass on the old version | rmz-oz | 1 | done in Sprint 1, PR [#61](https://github.com/rmz-oz/aculator/pull/61) |

### Planning (2026-11-05)

- Sprint 2 goal: get the LO/PO calculation running end-to-end, ship the first real views (course report, student profile), add roles and permissions, and reach the CSE 321 checkpoint on Nov 12.
- Carried over from Sprint 1: #6 (this board). Landed during the sprint: class diagram PR #65, Getting Real notes PR #59.

### Review (2026-11-12)

- 34 of 34 points done. #60 (1 point) was finished in Sprint 1 but only labelled for Sprint 2, so real Sprint 2 work is 33. Velocity so far: 20, 34. Average 27.
- Calculation, materialized views, roles, PO components and the course report run on Render from `main`.
- Mid semester slides and report presented in CSE 321 on Nov 12. The same slides cover CSE 311, which has no presentation date yet (#16).
- Found while preparing the slides, opened for Sprint 4: the course report does not read the materialized views (#79), changing a course's ECTS changes old reports (#80), `docker compose` starts only the database (#81). The free Render database expires on Dec 3 (#82).
- Student profile (#14) was in the Sprint 2 goal but not in the sprint, it is in Sprint 3.
- Nothing carries over.

`main` tagged `sprint-2` when this lands.

## Sprint 3 (2026-11-12 to 2026-11-19): Grade entry, student profile, login

| | points |
|---|---|
| Planned | 29 |

| # | Issue | Assignee | Points |
|---|---|---|---|
| [#13](https://github.com/rmz-oz/aculator/issues/13) | Bulk grade import from CSV | esinsarialtin | 5 |
| [#14](https://github.com/rmz-oz/aculator/issues/14) | Student PO profile page | ranayilmazz | 5 |
| [#15](https://github.com/rmz-oz/aculator/issues/15) | Index and table size measurements | sarginyaren | 3 |
| [#41](https://github.com/rmz-oz/aculator/issues/41) | How a score was computed | rmz-oz | 5 |
| [#42](https://github.com/rmz-oz/aculator/issues/42) | Not enough evidence state | esinsarialtin | 2 |
| [#43](https://github.com/rmz-oz/aculator/issues/43) | Property tests for the calculation | esinsarialtin | 2 |
| [#44](https://github.com/rmz-oz/aculator/issues/44) | Playwright tests and screenshots in CI | rmz-oz | 3 |
| [#72](https://github.com/rmz-oz/aculator/issues/72) | Missing grade vs absent | rmz-oz | 2 |
| [#77](https://github.com/rmz-oz/aculator/issues/77) | Login page for instructors and students | ranayilmazz | 2 |

### Planning (2026-11-12)

- Goal: an instructor logs in and enters grades (CSV, optical reader lists), a student sees their own PO profile, absent and not yet entered grades are told apart.
- 29 points, close to the average of 27.
- #16 (CSE 311 presentation) left the sprint: no presentation on Nov 17, it comes back when there is a new date.
- #17 and #18 were 8 points each and are split into sub-issues (#83, #84 and #85 to #87).