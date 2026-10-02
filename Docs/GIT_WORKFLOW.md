# 好学 — GIT WORKFLOW

## Repository

```text
https://github.com/joshuaJJM/ai_learning_agent
```

## Rules

1. Preserve existing Git history.
2. Do not force-push.
3. Commit after every completed Phase.
4. Commit messages should identify the Phase.
5. Never commit secrets.
6. Before commit, build or test the affected side.
7. Keep frontend/backend work separated enough that conflicts are easy to resolve.

## Suggested Working Style

For 48H speed, the team may use separate branches or separate working directories, but the exact branch policy is left to the team.

Before integration:

```bash
git status
git diff
git log --oneline -10
```

At the end of every Phase:

```bash
git add -A
git commit -m "phase-X: ..."
```

Push only after verifying that the commit contains no token, API key, `.env`, or private image/data artifact.
