# Version control in this project (Git)

## How it works

- **Commits** are snapshots of your project at a point in time. Each commit has a unique hash (e.g. `957ff50`) and a message.
- **History** is the chain of commits: you can see what changed, when, and go back to any snapshot.
- **Branches** are named lines of development. `main` is the default branch; you can create others (e.g. `feature/new-filter`) for experiments.
- **Tags** are fixed names for a specific commit. Use them for **releases** (e.g. `v0.1`, `v0.2`) so you can always refer to “version 0.1” later.

## Version numbering

We use **tags** to mark versions (e.g. `v0.1`). The current release is tagged in Git and optionally noted in the main README.

| Tag   | Meaning                    |
|-------|----------------------------|
| `v0.1`| First tracked release      |
| (future) `v0.2`, `v1.0`, … | Later releases |

## Useful commands

```bash
# See commit history
git log --oneline

# See which tag you have checked out
git describe --tags

# List all tags
git tag -l

# Check out a specific version (read-only)
git checkout v0.1

# Create a new tag (e.g. after more work)
git tag v0.2 -m "Release 0.2"
git push origin v0.2
```

## Workflow for a new release

1. Make and commit your changes on `main`.
2. Create a tag: `git tag v0.2 -m "Release 0.2"`.
3. Push the tag: `git push origin v0.2`.
