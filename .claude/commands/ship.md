You are helping the user segment, commit, and push their working tree changes in a clean, reviewable way. Follow these steps exactly and interactively — do not proceed to the next step without user approval.

## Step 1 — Understand the changes

Run these in parallel:
- `git status` (show all modified/untracked files)
- `git diff HEAD` (full diff of staged and unstaged changes)
- `git log --oneline -5` (recent commits, to match style)

Read the output carefully. For any untracked files shown in `git status`, also read their contents.

## Step 2 — Propose a commit split

Analyze the changes and group them into logical commits. Rules:
- If all changes are part of one cohesive feature or fix, propose a single commit.
- If changes span distinct concerns (e.g. a new feature + a bug fix + a config tweak), split into one commit per concern.
- Group by *semantic area*, not by file. Changes to a test file and the source file it tests belong in the same commit.
- Prefer fewer commits over many — only split when the concerns are genuinely independent.

Present the proposed split as a numbered list. For each group, show:
1. A one-line working title
2. The list of files (or hunks, if a single file has changes for two different concerns)

Then ask: **"Does this split look right? Say yes to continue, or describe any changes."**

Do not proceed until the user approves.

## Step 3 — Draft commit messages

For each commit group, draft a message following the conventions visible in `git log`:
- Imperative mood, lowercase, no trailing period
- First line ≤ 72 characters
- No body unless the change genuinely needs explanation

Present all messages together as a numbered list matching the groups from Step 2.

Then ask: **"Do these messages look good? Say yes to push, or suggest edits."**

Do not proceed until the user approves (or edits are made and re-approved).

## Step 4 — Create commits

For each group in order:
1. Stage exactly the files (or hunks) for that group using `git add <files>`.
   - If a file has changes split across two groups, use `git add -p <file>` to stage only the relevant hunks. Guide the user through this if needed.
2. Commit with the approved message using a heredoc to avoid shell escaping issues.
3. Verify with `git status` that only the intended changes were staged.

If any commit fails (e.g. hook rejection), stop, report the error, and ask how to proceed. Do NOT skip hooks with `--no-verify`.

## Step 5 — Push

Run `git push origin HEAD` to push to the current branch's remote.

Report success with the branch name and number of commits pushed. If the push is rejected (e.g. non-fast-forward), report the error and ask the user how to proceed — do not force push without explicit instruction.
