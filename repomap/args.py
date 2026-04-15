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
        description="Asterism 可以使用 AST 解析和 PageRank 排序生成 RepoMap 代码仓库地图",
        add_config_file_help=True,
        default_config_files=asterisk_config_files,
        config_file_parser_class=configargparse.YAMLConfigFileParser,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        ignore_unknown_config_file_keys=True,  # Ignore unknown keys like --model
    )

    # 相关信息
    group = parser.add_argument_group("相关信息")
    group.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="显示版本号",
    )

    # 输出设置
    group = parser.add_argument_group("输出设置")
    group.add_argument(
        "--show-repo-map",
        action="store_true",
        help="显示仓库地图",
        default=False,
    )
    group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="启用详细输出",
        default=False,
    )

    # RepoMap Token控制
    group = parser.add_argument_group("RepoMap Token控制")
    group.add_argument(
        "--model",
        metavar="MODEL",
        default=None,
        help="指定使用 RepoMap 的模型以匹配其 tokenizer （默认使用 gpt-4o 的 o200k_base 词表）",
    )
    group.add_argument(
        "--map-tokens",
        metavar="MAP_TOKENS",
        type=int,
        default=None,
        help="指定生成 RepoMap 的 token 数量上限（默认 4096）",
    )

    # RepoMap分析范围
    group = parser.add_argument_group("RepoMap分析范围")
    group.add_argument(
        "--subtree-only",
        action="store_true",
        help="指定纳入分析的子目录（默认分析整个仓库）",
        default=False,
    )
    group.add_argument(
        "--add-gitignore-files",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="是否将 .gitignore 里列的文件清单纳入分析范围（默认不纳入）",
    )
    default_asterismignore_file = (
        os.path.join(git_root, ".asterismignore") if git_root else ".asterismignore"
    )
    group.add_argument(
        "--asterismignore",
        metavar="FILE_NAME",
        type=lambda path_str: resolve_asterismignore_path(path_str, git_root),
        default=default_asterismignore_file,
        help="指定忽略规则文件（默认 .asterismignore ）",
    ).complete = shtab.FILE

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
