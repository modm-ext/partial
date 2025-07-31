# Helper Scripts for Submodule Management

Using git submodules is a good idea in theory. However, there are some pain
points in practice:

1. Including entire git repositories as submodules can cause very large
   downloads. Often we're only interested in a small subset of the code.
   We also do not care about the entire history of everything in the repository.

2. Repositories may include their own submodules, which may include their own
   submodules, which can cause significant issues when switching branches.
   The errors can be cryptic and hard to resolve.

3. Repositories may move or delete themselves or remove commits leaving
   your submodule reference hanging. This is becomes more of a problem as time
   progresses, often maintainers of repositories simply do not know of the
   trouble such often legitimate changes can cause downstream.


To solve these problems, we have created a set of scripts that allow us to hard
copy the files into our own repositories:

1. We copy only the files we need and only when a new release has been tagged.
   This means we can avoid downloading large repositories and their history.

2. We do not have to worry about submodules of submodules, as we flatten
   everything into a single directory structure.

3. We do not have to worry about repositories moving or deleting themselves,
   as we copy the files directly into our repository.


## CLI Usage

To partially copy sources out of a repository, specify its org/name and a list
of glob file patterns you want copied. For example, copying the license file
and the src folder of the TinyUSB repository:

```sh
wget -qL https://raw.githubusercontent.com/modm-ext/partial/main/partial.py
python3 partial.py -v hathach/TinyUSB LICENSE "src/**/*"
```

By default the destination is the current directory. You can specify a different
destination with the `--dest` option.

By default, the latest release tag or the highest numeric tag value is chosen as
the git branch. You can choose to use the latest default branch via the
`--head` option.

After the sources are copied, you can apply a git patch file using the `--patch`
option.


## GitHub Actions Configuration

A typical usage of this is in a `update.yml` workflow:

```yaml
name: Update

on:
  schedule:
    - cron:  '08 8 * * 3'
  workflow_dispatch:
  pull_request:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Configure Git
        run: |
          git config --global user.email "bot@modm.io"
          git config --global user.name "modm update bot"
      - name: Update repository
        env:
          GITHUB_TOKEN: ${{ github.token }}
        run: |
          wget -qL https://raw.githubusercontent.com/modm-ext/partial/main/partial.py
          python3 partial.py -v hathach/TinyUSB LICENSE "src/**/*"
      - name: Git push
      	if: github.ref == 'refs/heads/main'
        run: |
          git push origin main
```

Since GitHub disables workflows after 60 days of repo inactivity, the script
will automatically enable the workflow via the GitHub API if the `GITHUB_TOKEN`
is present in the environment. This effectively prevents the need to manually
reenable the workflow after a long period of inactivity.


## Python Usage

For more advanced use cases, the individual steps can be called from a custom
`update.py` script:

```python
import partial
# Reenable GitHub Action Workflow
partial.keepalive()

repo = "hathach/TinyUSB"
src = Path("TinyUSB_src")

# Clone the repo at the latest release
tag = partial.latest_release_tag(repo)
partial.clone_repo(repo, src, branch=tag)

# copy the files we need
files = partial.copy_files(src, ["LICENSE", "src/**/*"])
# optionally apply a patch afterwards
partial.apply_patch(patch)
# commit the files
partial.commit(files, tag)
```

Consult the source code for the API docs.
