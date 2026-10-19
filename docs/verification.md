# Verification record

Local checks performed on **18–19 October 2026**. This records what was actually executed; it is not a production, penetration-testing, or performance certification.

| Check                                            | Result                                                                                      |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Django database-backed test suite                | 77 tests passed on Python 3.12                                                              |
| Django system checks                             | Passed                                                                                      |
| Migration drift check                            | No changes detected                                                                         |
| Ruff lint and formatting                         | Passed                                                                                      |
| Django template indentation check                | Passed                                                                                      |
| JavaScript/CSS/document formatting               | Passed                                                                                      |
| Teacher/student browser journey                  | Passed                                                                                      |
| Autosave persists across reload                  | Passed in browser                                                                           |
| Stale-tab conflict stops overwrites              | Passed in browser                                                                           |
| Offline save failure and reconnect/retry         | Passed in browser                                                                           |
| Exam copy and question ordering                  | Passed in browser and backend tests                                                         |
| Invitation pause/reopen and code rotation        | Passed in browser and backend tests                                                         |
| Roster search/status filters and CSV             | Passed in browser; pagination and complete exports checked in backend tests                 |
| Question navigation and saved review marks       | Passed in browser and backend tests                                                         |
| Stale teacher review protection                  | HTTP 409 and preserved newer grades checked in browser and backend tests                    |
| 80 KB UTF-8 autosave, reload and submission      | Failed before keepalive fix; passed with byte-based keepalive selection                     |
| Full 50-question UTF-8 request                   | Reproduced request-limit rejection; 1.5 MB payload passed after limit adjustment            |
| Existing demo database migration                 | User/class/enrollment/exam/question/attempt/answer counts preserved; new defaults verified  |
| Mobile dashboard, builder and exam overflow      | None at 390px width                                                                         |
| Uncaught JavaScript errors in the tested journey | None                                                                                        |
| Production settings + static collection          | HTTPS login rendered and hashed CSS served; secure CSRF cookie and HSTS verified            |
| Container build/execution                        | Not run locally; Docker was unavailable                                                     |
| Remote GitHub Actions                            | Python/Chromium runs passed for merged features; inspect the Actions tab for a specific SHA |

The local browser journey used Playwright 1.62.1 with an explicit Chromium 141 executable because the default browser download endpoint was unavailable in the execution environment. CI installs the Chromium version matched to the pinned Playwright release.

`check --deploy` reports Django's W021 because HSTS preload enrollment is intentionally not enabled. The warning is not silenced. HTTPS redirect, secure cookies, HSTS, host checks, and a non-development secret are enabled in the production configuration.

The browser script creates an isolated database and removes it afterwards. Its screenshots are local test output rather than evidence of a publicly deployed service. The normal demo database and generated test outputs are excluded from version control.
