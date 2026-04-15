#!/usr/bin/env python

import argparse
import os
import sys
from pathlib import Path

import configargparse
import shtab

from repomap import __version__
from repomap.args_formatter import (
    DotEnvFormatter,
    MarkdownHelpFormatter,
    YamlHelpFormatter,
)


def resolve_asterismignore_path(path_str, git_root=None):
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
    elif git_root:
        return str(Path(git_root) / path)
    return str(path)


def get_parser(default_config_files, git_root):
    # Use asterism-specific config file to avoid conflicts with aider
    asterisk_config_files = []
    conf_fname = Path(".asterism.conf.yml")

    try:
        asterisk_config_files.append(conf_fname.resolve())  # CWD
    except OSError:
        pass

    if git_root:
        git_conf = Path(git_root) / conf_fname  # git root
        if git_conf not in asterisk_config_files:
            asterisk_config_files.append(git_conf)

    parser = configargparse.ArgumentParser(
        description="Asterism generates repository maps using AST parsing and PageRank ranking",
        add_config_file_help=True,
        default_config_files=asterisk_config_files,
        config_file_parser_class=configargparse.YAMLConfigFileParser,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        ignore_unknown_config_file_keys=True,  # Ignore unknown keys like --model
    )

    # Input files
    group = parser.add_argument_group("Input")
    group.add_argument(
        "files",
        metavar="FILE",
        nargs="*",
        help="Files or directories to analyze (optional)",
    ).complete = shtab.FILE

    # Model settings (minimal for repomap)
    group = parser.add_argument_group("Model Settings")
    group.add_argument(
        "--model",
        metavar="MODEL",
        default=None,
        help="Model name (for token counting, not required for repomap)",
    )
    group.add_argument(
        "files",
        metavar="FILE",
        nargs="*",
        help="Files or directories to analyze (optional)",
    ).complete = shtab.FILE

    # Repomap settings
    group = parser.add_argument_group("Repomap Settings")
    group.add_argument(
        "--map-tokens",
        type=int,
        default=None,
        help="Suggested number of tokens to use for repo map, use 0 to disable",
    )

    # File filtering
    group = parser.add_argument_group("File Filtering")
    group.add_argument(
        "--add-gitignore-files",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable/disable the addition of files listed in .gitignore to analysis scope",
    )
    default_asterismignore_file = (
        os.path.join(git_root, ".asterismignore") if git_root else ".asterismignore"
    )
    group.add_argument(
        "--asterismignore",
        metavar="ASTERISMIGNORE",
        type=lambda path_str: resolve_asterismignore_path(path_str, git_root),
        default=default_asterismignore_file,
        help="Specify the ignore file (default: .asterismignore in git root)",
    ).complete = shtab.FILE
    group.add_argument(
        "--subtree-only",
        action="store_true",
        help="Only consider files in the current subtree of the git repository",
        default=False,
    )

    # Output settings
    group = parser.add_argument_group("Output Settings")
    group.add_argument(
        "--show-repo-map",
        action="store_true",
        help="Display the repository map and exit",
        default=False,
    )
    group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (show processing details and token counts)",
        default=False,
    )

    # Version
    group = parser.add_argument_group("Information")
    group.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the version number and exit",
    )

    return parser


def get_sample_config():
    """Return sample .asterism.conf.yml file content."""
    return """# Asterism configuration file
# Create this file as .asterism.conf.yml in your project root

# Repomap settings
map-tokens: 4096

# File filtering
add-gitignore-files: false
asterismignore: .asterismignore
subtree-only: false

# Output
verbose: false
"""
