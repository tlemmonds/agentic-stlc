---
mode: testing
max_steps: 30
timeout: 420
target: ws
headless: true
---
# Session: SC-002_sc_002_sorted_tasks_by_due_date_on_nosecretformula_ve

## Step 1
On https://nosecretformula.vercel.app/ — Step 1 (SETUP): create a task titled 'Overdue 002' with due date 2026-05-10 using the Add a task form. Step 2 (SETUP): create a second task titled 'Future 002' with due date 2026-05-25. Step 3 (VERIFY): confirm the task list shows 'Overdue 002' pinned at the top of the list (above 'Future 002') because its due date is in the past relative to today's date 2026-05-17. Stop after the order is verified — do not delete the tasks.
