# Getting Real in this project

Principles from [Getting Real](https://basecamp.com/gettingreal) (37signals) we actually used, with the chapter and
where to see it. One line each, added when it happens. CSE 311 report section 6 is written from this file.

Everyone adds at least two of their own (#34).

| Chapter | What we did | Where | Who |
|---|---|---|---|
| 7. Fix Time and Budget, Flex Scope | Dates are fixed (12 and 17 Nov, 29 Dec) and sprints are one week; scope moves instead. The animated character has no sprint and only happens if there is time. | milestones, #40 | Ramiz |
| 8. Have an Enemy | We read the closest existing project (a Django CO-PO tool, IJERT 2025) and did the opposite where it breaks: it rounds between steps and ties LOs to the course. | decisions 0002, 0003 | Ramiz |
| 20. Make Opinionated Software | One way to weight outcomes (1 to 5 levels, ECTS across courses) instead of a settings page with every option. | decision 0004 | Ramiz |
| 29. Race to Running Software | The first pull request was a running Django app on PostgreSQL with CI; deployment came in the first sprint, before any feature. | #23, #30 | Ramiz |
| 10. Less Mass | Server rendered pages with HTMX instead of a separate React app: one language, one repo, one deploy. | decision 0006 | Ramiz |
| 13. Embrace Constraints | Four people and eight weeks: features were split into a plain, a recommended and an ambitious set, and we picked the middle one. | #41 to #57 | Ramiz |
| 60. Don't Do Dead Documents | No functional spec. Short decision notes, and the architecture diagram is a D2 file that is rendered again when the system changes. | docs/decisions, docs/architecture.d2 | Ramiz |
| 38. Meetings Are Toxic | Design questions go to GitHub Discussions and are closed with an answer; meetings are 30 minutes and only for planning. | Discussion #21 | Ramiz |
| 39. Seek and Celebrate Small Victories | Small pull requests that each close one issue, so something is merged every few days. | closed PRs | Ramiz |
| 62. Use Real Words | Mockups use the real Elif numbers from the guidelines, not placeholder text. | #41 | Ramiz |

Planned, add the row when it is done:

- 48. Three State Solution: "not enough evidence" as its own state next to a score and an empty state (#42).
- 34. Test in the Wild: five person user test (#55).
- 78. Zero Training: an instructor sets up a course without reading anything first.
