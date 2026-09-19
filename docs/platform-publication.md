# Platform publication boundary

The platform contains reusable code, reviewed technical documentation and
synthetic test fixtures. Keep real projects, generated images/prompts, private
notes, session logs and project acceptance evidence in a separate private vault.
Public examples must be fictional or explicitly approved for publication.
Preserve license and attribution notices.

## Check a change

Stage the intended files, then run:

```bash
python scripts/build_platform_tree.py --check
```

The check and its CI workflow reject forbidden or unreviewed tracked paths,
missing required public documents, and links to files outside the reviewed tree.
New documentation needs an explicit entry in `publication/platform-files.yaml`.
Ignoring a file does not remove an already tracked copy. Review content even
inside allowed code and fixture directories; this path check is not a secret
scanner.

## Prepare a public repository

Review and scan the current files, every branch/tag and all Git history for
credentials, private project material and personal author email addresses.
Review hosting metadata separately, including PRs, issues, comments, releases
and CI artifacts. Use an account-provided noreply address for future commits if
personal email should remain private.

Removing a file in a new commit leaves its old versions in Git. A history rewrite
changes commit identities and requires coordinating existing clones and branches.
It does not edit PR descriptions or guarantee removal of cached PR references
and comment edit history. For a fresh public release, a reviewed snapshot in a
new repository lets the existing development repository remain private.

The existing extraction command creates a snapshot and SHA-256 manifest from
the allow-list:

```bash
python scripts/build_platform_tree.py /tmp/platform-public-tree --strict
```

Choose an empty disposable destination: the extraction command replaces it.
Review the resulting tree before committing it to a new repository. Repository
visibility and any shared-history replacement are separate release decisions.
