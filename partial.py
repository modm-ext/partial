# Copyright (c) 2025, Niklas Hauser
# SPDX-License-Identifier: MPL-2.0

import os
import re
import json
import shutil
import logging
import argparse
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

LOGGER = logging.getLogger("partial")


def latest_release_tag(repo: str) -> str:
    """Returns the latest release tag of the repo."""
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/{repo}/releases/latest") as response:
            return json.loads(response.read())["tag_name"]
    except urllib.error.HTTPError:
        with urllib.request.urlopen(f"https://api.github.com/repos/{repo}/tags") as response:
            tags = [tag["name"] for tag in json.loads(response.read())]
            tags.sort(key=lambda v: tuple(map(int, re.findall(r"\d+", v))))
            return tags[-1]


def clone_repo(repo: str, dest: Path, branch: str = None, overwrite: bool = True):
    """
    Clones a GitHub repository of a branch to the specified destination.
    :param repo: GitHub repository in the format 'owner/repo'.
    :param dest: Destination path where the repository will be cloned.
    :param branch: Branch to clone. If None, the default branch is used.
    :param overwrite: If True, the destination directory will be removed if it exists.
    """
    if not overwrite and dest.exists():
        return
    shutil.rmtree(dest, ignore_errors=True)
    LOGGER.info("Cloning {}{}...".format(repo, "" if branch is None else f" at branch '{branch}'"))
    branch = "" if branch is None else f"--branch {branch}"
    subprocess.check_call("GIT_LFS_SKIP_SMUDGE=1 git -c advice.detachedHead=false clone --depth=1 "
                          f"{branch} https://github.com/{repo}.git {dest}", shell=True)


def copy_files(src: Path, patterns: list[str], dest: Path = None,
               delete: bool = True, modifier = None,
               binary: bool = False) -> list[Path]:
    """
    Copies files from the source directory matching the given patterns to the
    destination directory.

    :param src: Source directory to copy files from.
    :param patterns: List of glob patterns to match files.
    :param dest: Destination directory to copy files to. If None, uses `<src>_src`.
    :param delete: If True, deletes the destination directory before copying files.
    :param modifier: Optional function to modify the content of the files before copying.
                     If None, no modification is applied.
    :param binary: If True, files are copied in binary mode.
    :return: List of copied file paths.
    """
    if modifier is None: modifier = lambda v: v
    LOGGER.info("Copying files...")
    if delete:
        if dest is None:
            dest = Path(".")
            files = []
            for pattern in patterns:
                for fdest in dest.glob(pattern):
                    files.append(fdest)
            for top_path in set(Path(f.parts[0]) for f in files):
                LOGGER.debug(f"Removing '{top_path}'...")
                if top_path.is_file():
                    top_path.unlink()
                else:
                    shutil.rmtree(top_path, ignore_errors=True)
        else:
            LOGGER.debug(f"Removing '{dest}'...")
            shutil.rmtree(dest, ignore_errors=True)

    # Find all the files we want to copy
    files = []
    for pattern in patterns:
        for fsrc in src.glob(pattern):
            if not fsrc.is_file(): continue
            fdest = fsrc.relative_to(src)
            if dest is not None: fdest = dest / fdest
            fdest.parent.mkdir(parents=True, exist_ok=True)
            LOGGER.debug(fdest)
            if binary:
                shutil.copy2(fsrc, fdest)
            else:
                # Copy, normalize newline and remove trailing whitespace
                with (fsrc.open("r", newline=None, encoding="utf-8", errors="replace") as rfile,
                      fdest.open("w", encoding="utf-8") as wfile):
                    wfile.writelines(modifier(l.rstrip())+"\n" for l in rfile.readlines())
            files.append(fdest)

    assert files, "No files copied!"
    return files


def apply_patch(file: Path):
    """
    Applies a git patch file to the current repository.
    """
    LOGGER.info(f"Apply patch '{file}'...")
    subprocess.check_call(f"git apply -v --ignore-whitespace {file}", shell=True)



def commit(files: list[Path], tag: str = None):
    """
    Commits the specified files to the current git repository.
    :param files: List of file paths to commit.
    :param tag: Optional tag to include in the commit message.
    """
    files = set(f.parts[0] for f in files)
    LOGGER.info(f"Committing {', '.join(files)}...")
    subprocess.check_call(f"git add {' '.join(files)}", shell=True)
    if subprocess.call("git diff-index --quiet HEAD --", shell=True):
        if tag is None: tag = "latest"
        if tag[0].isdigit(): tag = f"v{tag}"
        subprocess.run(f'git commit -m "Update to {tag}"', shell=True)



def copy_repo(repo: str, patterns: list[str], dest: Path = None,
              patch: Path = None, fast: bool = True, head: bool = False,
              binary: bool = False):
    """
    Copies files from a GitHub repository to the specified destination directory.
    :param repo: GitHub repository in the format 'owner/repo'.
    :param patterns: List of glob patterns to match files.
    :param dest: Destination directory to copy files to. If None, uses `<repo>_src`.
    :param patch: Optional path to a git patch file to apply after copying files.
    :param fast: If True, skips cloning the repository and assumes it is already cloned.
    :param head: If True, uses the latest commit on the default branch instead of the latest release.
    :param binary: If True, files are copied in binary mode.
    """
    src = Path(f"{repo.rsplit('/')[-1]}_src")
    tag = None if head else latest_release_tag(repo)
    clone_repo(repo, src, tag, overwrite=not fast)
    files = copy_files(src, patterns, dest, binary=binary)
    if patch: apply_patch(patch)
    commit(files, tag)


def replace_key(text: str, key: str, content: str) -> str:
    """
    Replaces a key in the format `<!--{key}-->{content}<!--/{key}-->` in the
    text with the given content.

    :param text: The original text.
    :param key: The key to replace.
    :param content: The content to replace the key with.
    :return: The modified text with the key replaced.
    """
    return re.sub(r"<!--{0}-->.*?<!--/{0}-->".format(key),
                  "<!--{0}-->\n{1}\n<!--/{0}-->".format(key, content),
                  text, flags=re.DOTALL | re.MULTILINE)


def keepalive(workflows: list[Path] = None):
    """
    Keep all workflows alive by enabling them using the GitHub CLI.
    :param workflows: List of workflow files to enable. If None, defaults to all
                      YAML files in `.github/workflows`.
    """
    if "GITHUB_TOKEN" in os.environ:
        LOGGER.info("Keepalive all workflows...")
        if workflows is None:
            workflows = Path(".github/workflows").glob("*.y*ml")
        for workflow in workflows:
            workflow = f"repos/${{GITHUB_REPOSITORY}}/actions/workflows/{workflow.name}/enable"
            workflow = f'gh api --silent -X PUT {workflow}'
            LOGGER.debug(workflow)
            subprocess.run(workflow, shell=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy files from a GitHub repository.")
    parser.add_argument("repo", help="GitHub repository in the format 'owner/repo'")
    parser.add_argument("patterns", nargs="+", help="Glob patterns to match files")
    parser.add_argument("--head", action="store_true", help="Use the latest commit on the default branch instead of the latest release")
    parser.add_argument("--patch", type=Path, default=None, help="Path to a git patch file to apply")
    parser.add_argument("--dest", type=Path, default=None, help="Destination directory (default: repo_name_src)")
    parser.add_argument("--fast", action="store_true", help="Do not clone the repository, assume it is already cloned")
    parser.add_argument("--bin", action="store_true", help="Copy files in binary mode")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    keepalive()

    copy_repo(args.repo, args.patterns, args.dest, args.patch,
              args.fast, args.head, args.bin)

