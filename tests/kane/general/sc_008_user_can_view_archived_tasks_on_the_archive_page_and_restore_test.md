---
mode: testing
max_steps: 30
timeout: 420
target: ws
headless: true
---
# Session: SC-008_sc_008_user_can_view_archived_tasks_on_the_archive_pa

## Step 1
On https://nosecretformula.vercel.app/ — Step 1 (SETUP): create a new task titled 'Archive demo task' with due date 2026-05-20 using the Add a task form. Step 2 (SETUP): on that task's row, click the Archive button to archive it. Step 3 (VERIFY): click the Archive link in the top navigation (or navigate to https://nosecretformula.vercel.app/archive) and confirm 'Archive demo task' is listed there. Step 4 (VERIFY): click the Restore button next to that archived task. Step 5 (VERIFY): return to the main task list (navigate to https://nosecretformula.vercel.app/) and confirm 'Archive demo task' is back in the active list. Stop after the restored task is visible on the active list — do not delete or re-archive it.
