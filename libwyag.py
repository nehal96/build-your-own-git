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
class GitRepository (object):
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


# At its core, Git is a “content-addressed filesystem”. That means that unlike
# regular filesystems, where the name of a file is arbitrary and unrelated to
# that file’s contents, the names of files as stored by Git are mathematically
# derived from their contents. Git uses objects to store the actual files it
# keeps in version control (eg. source code), commits, tags, and others.
class GitObject (object):
    repo = None

    def __init__(self, repo, data=None):
        self.repo = repo

        if data != None:
            self.deserialize(data)

    def serialize(self):
        """This function must be implemented by subclasses.

        It must read the object's contents from self.data, a byte string, and
        do whatever it takes to convert it into a meaningful representation.
        What exactly that means depends on each subclass."""
        raise Exception("Unimplemented!")

    def deserialize(self):
        raise Exception("Unimplemented!")

# To read an object, we need to know its hash. The path is computed from this
# hash (first two characters, then a directory delimiter /, then the
# remaining part) and used to look it up inside the “objects” directory in the
# gitdir. For example, the path to e673d1b7eaa0aa01b5bc2442d570a765bdaae751 is
# .git/objects/e6/73d1b7eaa0aa01b5bc2442d570a765bdaae751
# The file is then read as a binary file, and decompressed using zlib. From
# the decompressed data, the two header components are extracted: the object type
# and its size. From the type, the actual class to use is determined. The size
# is converted to a Python integer, and it's checked if it matches. Then the
# correct constructor for that object’s format is called.
def object_read(repo, sha):
    """Read object object_id from Git repository. Return a GitObject whose
    exact type depends on the object."""

    # Get object's path
    path = repo_file(repo, "objects", sha[0:2], sha[2:])

    with open(path, "rb") as f:
        # Decompress binary file
        raw = zlib.decompress(f.read())

        # Read object type
        x = raw.find(b' ')
        fmt = raw[0:x]

        # Read and validate object size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw) - y - 1:
            raise Exception("Malformed object {0}: bad length".format(sha))

        # Pick constructor
        if   fmt == b'commit'  : c = GitCommit
        elif fmt == b'tree'    : c = GitTree
        elif fmt == b'tag'     : c = GitTag
        elif fmt == b'blob'    : c = GitBlob
        else:
            raise Exception("Unknown type %s for object %s".format(fmt.decode("ascii"), sha))

        # Call constructor and return object
        return c(repo, raw[y+1:])

# Placeholder function to find an object. Currently objects can only be found by
# its full hash, but a full implementation will allow objects to be found by
# other references like short hashes and tags.
def object_find(repo, name, fmt=None, follow=True):
    return name

# Writing an object is reading in reverse: insert the header, compute the hash,
# compress everything, and write the result.
def object_write(obj, actually_write=True):
    # Serialize object data
    data = obj.serialize()
    # Add header
    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data
    # Compute hash
    sha = hashlib.sha1(result).hexdigest()

    if actually_write:
        # Compute path
        path = repo_file(obj.repo, "objects", sha[0:2], sha[2:], mkdir=actually_write)

        with open(path, 'wb') as f:
            # Compress and write
            f.write(zlib.compress(result))

    return sha
