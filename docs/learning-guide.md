# Learn the project, then make it yours

This project was developed with AI assistance. Treat the repository as a starting point for understanding and practical work. Before describing any part as your own expertise, run it, change it, break it, and explain its behavior without reading the answer from a screen.

## Read in this order

1. `classroom/models.py`: draw the relationship between a course, exam, attempt and answer. Explain why the attempt and enrollment uniqueness constraints exist.
2. `classroom/services.py`: follow one answer save. Identify where the student identity comes from, what happens on a stale revision, and why late answer bodies are ignored.
3. `classroom/views.py`: trace the owner/enrollment filters. Try to replace an attempt ID in the URL while signed in as a different student.
4. `classroom/forms.py`: inspect validation for choice questions, date windows and points.
5. `static/attempt.js`: explain dirty state, a request in flight, a pending submit, and the 409 conflict path.
6. `classroom/tests/test_workflows.py`: pick five tests, predict their results, then introduce a bug that makes each fail.

## Hands-on exercises

### First session: run and inspect

Run the demo. Use separate browser profiles for teacher and student. Create an exam, submit it, grade its written question, and release results. Inspect browser Network requests: identify the CSRF header and revision number. Verify that no answer key is present before results are released.

### Second session: change a real behavior

Add a short, optional class announcement. Decide which model owns it, create a migration, validate its length, show it to enrolled students, and test that a different teacher cannot edit it. Make a real feature branch and explain its diff before committing it.

### Third session: investigate a failure

Open the same attempt in two tabs. Save different answers in each and explain the conflict. Turn network access off while typing. Explain why the UI cannot honestly say an answer is saved until the server acknowledges it. Set an attempt deadline in the past in a local shell and inspect the late-payload behavior.

## Questions to be able to answer

- How is authentication different from checking ownership of an exam?
- Why must the correct answer remain on the server until results are released?
- Why is a countdown insufficient to enforce an exam deadline?
- Why does a transaction matter if a payload contains several answers?
- What does SQLite's `IMMEDIATE` transaction mode do? What would change with PostgreSQL?
- Why does the autosave endpoint return 409 instead of overwriting an answer from another tab?
- Which fields can a student register or submit, and which fields are server-owned?
- How could a CSV cell become a formula, and how does the export reduce that risk?
- What happens if the browser closes and the expiry command does not run immediately?
- Which parts would you redesign for 5,000 simultaneous students?

## Describe the work accurately

A truthful project description is: **“An exam-management learning project built with Django, SQLite and JavaScript, developed with AI assistance. I used it to study authentication, authorization, transactions, timed workflows and testing, and implemented [the specific changes you actually made].”**

Update that description as your own understanding and contributions grow. Do not claim production users, deployment experience, independent authorship, or performance measurements that you have not actually established.
