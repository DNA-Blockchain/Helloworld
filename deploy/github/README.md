# The organization's public profile page

[`profile/README.md`](profile/README.md) is the page GitHub shows on
[github.com/DNA-Blockchain](https://github.com/DNA-Blockchain). GitHub reads it from a **public** repository
named `.github`, at the path `profile/README.md`, so the copy here is the source and that repo is the
deployment target.

It lives in this repository so it's reviewed and versioned with the code it describes, and so
`tests/test_authorship.py` can catch a version number that has gone stale.

Publish a change after merging it here:

```bash
gh api repos/DNA-Blockchain/.github/contents/profile/README.md \
  --method PUT -f message="Update the profile page" \
  -f content="$(base64 -w0 deploy/github/profile/README.md)" \
  -f sha="$(gh api repos/DNA-Blockchain/.github/contents/profile/README.md --jq .sha)"
```

Only public, already-published facts belong on that page: no tokens, no private repository names, and
nothing personal (`NOTICE.md`, `PRIVACY.md`).
