import argparse
import collections
import configparser
import hashlib
import os
import re
import sys
import zlib

# Used to work with command-line arguments
argparser = argparse.ArgumentParser(description="This stupid content tracker")

# Used to handle subcommands (like git init, commit, etc.)
# The `dest="command"` argument states that the name of the chosen subparser
# will be returned as a string in a field called "command".
argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
# Require one (git COMMAND)
argsubparsers.required = True

# Call the function based on the subcommand/subparser string
def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)

    if   args.command == "add"         : cmd_add(args)
    elif args.command == "cat-file"    : cmd_cat_file(args)
    elif args.command == "checkout"    : cmd_checkout(args)
    elif args.command == "commit"      : cmd_commit(args)
    elif args.command == "hash-object" : cmd_hash_object(args)
    elif args.command == "init"        : cmd_init(args)
    elif args.command == "log"         : cmd_log(args)
    elif args.command == "ls-tree"     : cmd_ls_tree(args)
    elif args.command == "merge"       : cmd_merge(args)
    elif args.command == "rebase"      : cmd_rebase(args)
    elif args.command == "rev-parse"   : cmd_rev_parse(args)
    elif args.command == "rm"          : cmd_rm(args)
    elif args.command == "show-ref"    : cmd_show_ref(args)
    elif args.command == "tag"         : cmd_tag(args)


# An abstraction of a repository.
# A git repository is made of 2 things: a "work tree", where the files meant to
# be in version control live, and a "git directory", where Git stores its own
# data.
class GitRepository(object):
    """A git repository"""

    worktree = None
    gitdir = None
    conf = None

    # Optional force argument that disables all checks
    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        # Verify that the directory exists and that contains a subdirectory
        # called `.git`
        if not (force or os.path.isdir(self.gitdir)):
            raise Exception("Not a Git repository %s" % path)

        # Read configuration file in .git/config
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file is missing.")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0 and not force:
                raise Exception("Unsupported repositoryformatversion %s" % vers)


def repo_path(repo, *path):
    """Compute path under repo's gitdir"""
    return os.path.join(repo.gitdir, *path)

def repo_file(repo, *path, mkdir=False):
    """Same as repo_path, but create dirname(*path) is absent. For example,
    repo_file(r, \"refs\", \"remotes\", \"origin\", \"HEAD\") will create
    .git/refs/remotes/origin"""

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)

def repo_dir(repo, *path, mkdir=False):
    """Same as repo_path, but mkdir *path is absent if mkdir"""

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if (os.path.isdir(path)):
            return path
        else:
            raise Exception("Not a directory %s" % path)

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None

# To create a new repository, start with a directory (create one if it doesn't
# exist, or check for emptiness otherwise) and create the following paths:
# .git (git directory) with contains:
#    .git/objects/      : the objects store.
#    .git/refs/         : the reference store, which has to subdirectories: `heads`
#                         and `tags`
#    .git/HEAD          : a reference to the current HEAD
#    .git/config        : the repo's config file
#    .git/description   : the repo's description file
def repo_create(path):
    """Create a new repository at path"""

    repo = GitRepository(path, True)

    # First we make sure that the path either doesn't exist or is an empty dir
    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception("%s is not a directory!" % path)
        if not os.listdir(repo.worktree):
            raise Exception("%s is not empty" % path)
    else:
        os.makedirs(repo.worktree)

    assert(repo_dir(repo, "branches", mkdir=True))
    assert(repo_dir(repo, "objects", mkdir=True))
    assert(repo_dir(repo, "refs", "tags", mkdir=True))
    assert(repo_dir(repo, "refs", "heads", mkdir=True))

    # .git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository: edit this file 'description' to name the repository.\n")

    # .git/HEAD
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo

# A simple configiration file with 3 fields:
# repositoryformatversion = 0   : the version of the gitdir format. 0 means the
#                                 inital format, 1 is the same with extensions.
#                                 If > 1, git panics. wyag will only accept 0.
# filemode = true               : Disable tracking of file mode changes in the
#                                 work tree.
# bare = false                  : Indicates that this repo has a worktree.
def repo_default_config():
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

# Subparser command to handle command argument for `wyag init [path]`
argsp = argsubparsers.add_parser("init", help="Initialize a new, empty repository.")
argsp.add_argument("path",
                   metavar="directory",
                   nargs="?",
                   default=".",  # Default path is .
                   help="Where to create this repository")

# 'Bridge' function that will read argument values from the object returned by
# argparse and call the actual function with correct values
def cmd_init(args):
    repo_create(args.path)

# This function will look for a repository, starting at the current directory
# and recursing back until '/'. To identify something as a repo, it will look
# for the presence of a `.git` directory.
# Almost all git functions, except `init`, use an existing repo, so this
# function is used for that.
def repo_find(path=".", required=True):
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)

    # If we haven't returned, recurse in parent, if w
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        # Bottom case
        # os.path.join("/", "..") == "/":
        # If parent == path, then path is root.
        if required:
            raise Exception("No git directory.")
        else:
            return None

    # Recursive case
    return repo_find(parent, required)
