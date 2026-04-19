import json
import os
import re
import sys
from dataclasses import fields
from pathlib import Path

try:
    import git
except ImportError:
    git = None

from repomap import models
from repomap.args import get_parser
from repomap.io import InputOutput
from repomap.llm import litellm  # noqa: F401; properly init litellm on launch
from repomap.models import ModelSettings
from repomap.repo import ANY_GIT_ERROR, GitRepo
from repomap.repomap import RepoMap
from repomap.report import report_uncaught_exceptions


def check_config_files_for_yes(config_files):
    found = False
    for config_file in config_files:
        if Path(config_file).exists():
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        if line.strip().startswith("yes:"):
                            print("Configuration error detected.")
                            print(f"The file {config_file} contains a line starting with 'yes:'")
                            print("Please replace 'yes:' with 'yes-always:' in this file.")
                            found = True
            except Exception:
                pass
    return found


def get_git_root():
    """Try and guess the git repo, since the conf.yml can be at the repo root"""
    try:
        repo = git.Repo(search_parent_directories=True)
        return repo.working_tree_dir
    except (git.InvalidGitRepositoryError, FileNotFoundError):
        return None


def guessed_wrong_repo(io, git_root, fnames, git_dname):
    """After we parse the args, we can determine the real repo. Did we guess wrong?"""

    try:
        check_repo = Path(GitRepo(io, fnames, git_dname).root).resolve()
    except (OSError,) + ANY_GIT_ERROR:
        return

    # we had no guess, rely on the "true" repo result
    if not git_root:
        return str(check_repo)

    git_root = Path(git_root).resolve()
    if check_repo == git_root:
        return

    return str(check_repo)


def make_new_repo(git_root, io):
    try:
        repo = git.Repo.init(git_root)
        check_gitignore(git_root, io, False)
    except ANY_GIT_ERROR as err:  # issue #1233
        io.tool_error(f"Unable to create git repo in {git_root}")
        io.tool_output(str(err))
        return

    io.tool_output(f"Git repository created in {git_root}")
    return repo


def setup_git(git_root, io):
    if git is None:
        return

    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None

    repo = None

    if git_root:
        try:
            repo = git.Repo(git_root)
        except ANY_GIT_ERROR:
            pass
    elif cwd == Path.home():
        io.tool_warning(
            "You should probably run aider in your project's directory, not your home dir."
        )
        return
    elif cwd and io.confirm_ask(
        "No git repo found, create one to track aider's changes (recommended)?"
    ):
        git_root = str(cwd.resolve())
        repo = make_new_repo(git_root, io)

    if not repo:
        return

    try:
        user_name = repo.git.config("--get", "user.name") or None
    except git.exc.GitCommandError:
        user_name = None

    try:
        user_email = repo.git.config("--get", "user.email") or None
    except git.exc.GitCommandError:
        user_email = None

    if user_name and user_email:
        return repo.working_tree_dir

    with repo.config_writer() as git_config:
        if not user_name:
            git_config.set_value("user", "name", "Your Name")
            io.tool_warning('Update git name with: git config user.name "Your Name"')
        if not user_email:
            git_config.set_value("user", "email", "you@example.com")
            io.tool_warning('Update git email with: git config user.email "you@example.com"')

    return repo.working_tree_dir


def check_gitignore(git_root, io, ask=True):
    if not git_root:
        return

    try:
        repo = git.Repo(git_root)
        patterns_to_add = []

        if not repo.ignored(".aider"):
            patterns_to_add.append(".aider*")

        env_path = Path(git_root) / ".env"
        if env_path.exists() and not repo.ignored(".env"):
            patterns_to_add.append(".env")

        if not patterns_to_add:
            return

        gitignore_file = Path(git_root) / ".gitignore"
        if gitignore_file.exists():
            try:
                content = io.read_text(gitignore_file)
                if content is None:
                    return
                if not content.endswith("\n"):
                    content += "\n"
            except OSError as e:
                io.tool_error(f"Error when trying to read {gitignore_file}: {e}")
                return
        else:
            content = ""
    except ANY_GIT_ERROR:
        return

    if ask:
        io.tool_output("You can skip this check with --no-gitignore")
        if not io.confirm_ask(f"Add {', '.join(patterns_to_add)} to .gitignore (recommended)?"):
            return

    content += "\n".join(patterns_to_add) + "\n"

    try:
        io.write_text(gitignore_file, content)
        io.tool_output(f"Added {', '.join(patterns_to_add)} to .gitignore")
    except OSError as e:
        io.tool_error(f"Error when trying to write to {gitignore_file}: {e}")
        io.tool_output(
            "Try running with appropriate permissions or manually add these patterns to .gitignore:"
        )
        for pattern in patterns_to_add:
            io.tool_output(f"  {pattern}")



def main(argv=None, input=None, output=None, force_git_root=None):
    report_uncaught_exceptions()

    if argv is None:
        argv = sys.argv[1:]

    if git is None:
        git_root = None
    elif force_git_root:
        git_root = force_git_root
    else:
        git_root = get_git_root()

    conf_fname = Path(".aider.conf.yml")

    default_config_files = []
    try:
        default_config_files += [conf_fname.resolve()]  # CWD
    except OSError:
        pass

    if git_root:
        git_conf = Path(git_root) / conf_fname  # git root
        if git_conf not in default_config_files:
            default_config_files.append(git_conf)
    default_config_files.append(Path.home() / conf_fname)  # homedir
    default_config_files = list(map(str, default_config_files))

    parser = get_parser(default_config_files, git_root)
    try:
        args, _ = parser.parse_known_args(argv)
    except AttributeError as e:
        if all(word in str(e) for word in ["bool", "object", "has", "no", "attribute", "strip"]):
            if check_config_files_for_yes(default_config_files):
                return 1
        raise e

    if args.verbose:
        print("Config files search order, if no --config:")
        for file in default_config_files:
            exists = "(exists)" if Path(file).exists() else ""
            print(f"  - {file} {exists}")

    default_config_files.reverse()

    parser = get_parser(default_config_files, git_root)

    args, _ = parser.parse_known_args(argv)

    # Parse final arguments
    args = parser.parse_args(argv)

    # Shell completions - removed
    # if args.shell_completions:
    #     parser.prog = "asterism"
    #     print(shtab.complete(parser, shell=args.shell_completions))
    #     sys.exit(0)

    # Analytics - removed
    # if args.analytics_disable:
    #     analytics = Analytics(permanently_disable=True)
    #     print("Analytics have been permanently disabled.")

    # SSL verification - removed
    # if not args.verify_ssl:
    #     import httpx
    #     os.environ["SSL_VERIFY"] = ""
    #     litellm._load_litellm()
    #     litellm._lazy_module.client_session = httpx.Client(verify=False)
    #     litellm._lazy_module.aclient_session = httpx.AsyncClient(verify=False)
    #     models.model_info_manager.set_verify_ssl(False)

    # Timeout - removed
    # if args.timeout:
    #     models.request_timeout = args.timeout

    # Color modes - removed
    # if args.dark_mode:
    #     args.user_input_color = "#32FF32"
    #     args.tool_error_color = "#FF3333"
    #     args.tool_warning_color = "#FFFF00"
    #     args.assistant_output_color = "#00FFFF"
    #     args.code_theme = "monokai"
    #
    # if args.light_mode:
    #     args.user_input_color = "green"
    #     args.tool_error_color = "red"
    #     args.tool_warning_color = "#FFA500"
    #     args.assistant_output_color = "blue"
    #     args.code_theme = "default"

    # Editing mode - removed
    # if return_coder and args.yes_always is None:
    #     args.yes_always = True
    #
    # editing_mode = EditingMode.VI if args.vim else EditingMode.EMACS

    def get_io(pretty=True):
        return InputOutput(
            pretty=pretty,
            yes=True,  # Default for repomap
            input=input,
            output=output,
            encoding=args.encoding if hasattr(args, 'encoding') else 'utf-8',
        )

    io = get_io(True)  # Enable pretty output for repomap

    # Environment variables and API keys - removed (not needed for repomap)
    # if args.set_env:
    #     for env_setting in args.set_env:
    #         try:
    #             name, value = env_setting.split("=", 1)
    #             os.environ[name.strip()] = value.strip()
    #         except ValueError:
    #             io.tool_error(f"Invalid --set-env format: {env_setting}")
    #             io.tool_output("Format should be: ENV_VAR_NAME=value")
    #             return 1
    #
    # # Process any API keys set via --api-key
    # if args.api_key:
    #     for api_setting in args.api_key:
    #         try:
    #             provider, key = api_setting.split("=", 1)
    #             env_var = f"{provider.strip().upper()}_API_KEY"
    #             os.environ[env_var] = key.strip()
    #         except ValueError:
    #             io.tool_error(f"Invalid --api-key format: {api_setting}")
    #             io.tool_output("Format should be: provider=key")
    #             return 1

    # API key handling removed - not needed for repomap functionality
    # if args.anthropic_api_key:
    #     os.environ["ANTHROPIC_API_KEY"] = args.anthropic_api_key
    # if args.openai_api_key:
    #     os.environ["OPENAI_API_KEY"] = args.openai_api_key

    # Handle deprecated model shortcut args - removed
    # handle_deprecated_model_args(args, io)

    # OpenAI API settings - removed
    # if args.openai_api_base:
    #     os.environ["OPENAI_API_BASE"] = args.openai_api_base
    # if args.openai_api_version:
    #     io.tool_warning(
    #         "--openai-api-version is deprecated, use --set-env OPENAI_API_VERSION=<value>"
    #     )
    #     os.environ["OPENAI_API_VERSION"] = args.openai_api_version
    # if args.openai_api_type:
    #     io.tool_warning("--openai-api-type is deprecated, use --set-env OPENAI_API_TYPE=<value>")
    #     os.environ["OPENAI_API_TYPE"] = args.openai_api_type
    # if args.openai_organization_id:
    #     io.tool_warning(
    #         "--openai-organization-id is deprecated, use --set-env OPENAI_ORGANIZATION=<value>"
    #     )
    #     os.environ["OPENAI_ORGANIZATION"] = args.openai_organization_id

    # Analytics - disabled for repomap
    # File handling for repomap
    fnames = []  # asterism doesn't use file focusing like aider

    git_dname = None

    # We can't know the git repo for sure until after parsing the args.
    # If we guessed wrong, reparse because that changes things like
    # the location of the config.yml and history files.
    if not force_git_root and git is not None:
        right_repo_root = guessed_wrong_repo(io, git_root, fnames, git_dname)
        if right_repo_root:
            # analytics.event("exit", reason="Recursing with correct repo")
            return main(argv, input, output, right_repo_root)

    git_root = setup_git(git_root, io)
    # gitignore checking removed
    # if args.gitignore:
    #     check_gitignore(git_root, io)

    if args.verbose:
        # show = format_settings(parser, args)
        # io.tool_output(show)
        pass  # format_settings not needed for repomap

    cmd_line = " ".join(sys.argv)
    # cmd_line = scrub_sensitive_info(args, cmd_line)
    io.tool_output(cmd_line, log_only=True)

    # Version checking and imports - removed
    # is_first_run = is_first_run_of_new_version(io, verbose=args.verbose)
    # check_and_load_imports(io, is_first_run, verbose=args.verbose)
    #
    # register_models(git_root, args.model_settings_file, io, verbose=args.verbose)
    # register_litellm_models(git_root, args.model_metadata_file, io, verbose=args.verbose)
    #
    # if args.list_models:
    #     models.print_matching_models(io, args.list_models)
    #     analytics.event("exit", reason="Listed models")
    #     return 0

    # Command line aliases - removed
    # if args.alias:
    #     for alias_def in args.alias:
    #         # Split on first colon only
    #         parts = alias_def.split(":", 1)
    #         if len(parts) != 2:
    #             io.tool_error(f"Invalid alias format: {alias_def}")
    #             io.tool_output("Format should be: alias:model-name")
    #             analytics.event("exit", reason="Invalid alias format error")
    #             return 1
    #         alias, model = parts
    #         models.MODEL_ALIASES[alias.strip()] = model.strip()

    # OpenRouter API key check - removed
    # if args.model.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
    #     io.tool_warning(
    #         f"The specified model '{args.model}' requires an OpenRouter API key, which was not"
    #         " found."
    #     )
    #     # Attempt OAuth flow because the specific model needs it
    #     if offer_openrouter_oauth(io, analytics):
    #         # OAuth succeeded, the key should now be in os.environ.
    #         # Check if the key is now present after the flow.
    #         if os.environ.get("OPENROUTER_API_KEY"):
    #             io.tool_output(
    #                 "OpenRouter successfully connected."
    #             )  # Inform user connection worked
    #         else:
    #             # This case should ideally not happen if offer_openrouter_oauth succeeded
    #             # but check defensively.
    #             io.tool_error(
    #                 "OpenRouter authentication seemed successful, but the key is still missing."
    #             )
    #             analytics.event(
    #                 "exit",
    #                 reason="OpenRouter key missing after successful OAuth for specified model",
    #             )
    #             return 1
    #     else:
    #         # OAuth failed or was declined by the user
    #         io.tool_error(
    #             f"Unable to proceed without an OpenRouter API key for model '{args.model}'."
    #         )
    #         io.offer_url(urls.models_and_keys, "Open documentation URL for more info?")
    #         analytics.event(
    #             "exit",
    #             reason="OpenRouter key missing for specified model and OAuth failed/declined",
    #         )
    #         return 1

    # Create minimal model for repomap (no LLM needed)
    if args.model:
        main_model = models.Model(
            args.model,
            weak_model=None,  # Not needed for repomap
            editor_model=None,  # Not needed for repomap
            editor_edit_format=None,  # Not needed for repomap
            verbose=args.verbose,
        )
    else:
        # Create a minimal mock model
        class MinimalModel:
            def __init__(self):
                self.name = "minimal"
                self.info = {"max_input_tokens": 128000}  # Default large value
                self.edit_format = "ask"  # Use "ask" to match AskCoder
                self.use_repo_map = True
                self.max_chat_history_tokens = 128000
                # Use accurate token counting with litellm
                self.token_count = self._token_count
                self.reasoning_tag = None  # No reasoning for repomap
                self.streaming = True  # Support streaming
                self.thinking_tokens = 0  # No thinking tokens
                self.reasoning_effort = None  # No reasoning effort
                self.caches_by_default = False  # No caching
                # Add missing ModelSettings attributes
                self.weak_model_name = None
                self.send_undo_reply = False
                self.lazy = False
                self.overeager = False
                self.reminder = "user"
                self.examples_as_sys_msg = False
                self.extra_params = None
                self.cache_control = False
                self.use_system_prompt = True
                self.use_temperature = True
                self.editor_model_name = None
                self.editor_edit_format = None
                self.remove_reasoning = None
                self.system_prompt_prefix = None
                self.accepts_settings = []  # Empty list for minimal model

            def _token_count(self, text):
                """Accurate token counting using litellm."""
                if not text:
                    return 0
                try:
                    # Use litellm.token_counter for accurate counting
                    # Use a generic model name that should work with litellm
                    return litellm.token_counter(model="gpt-4o", text=text)
                except Exception:
                    # Fallback to character-based estimation if litellm fails
                    # Approx 4 characters per token for code
                    return len(text) // 4

            def commit_message_models(self):
                return [self]
            def weak_model(self):
                # Return self instead of self for repomap
                return self
            def get_repo_map_tokens(self):
                map_tokens = 4096
                max_inp_tokens = self.info.get("max_input_tokens")
                if max_inp_tokens:
                    map_tokens = max_inp_tokens / 8
                    map_tokens = min(map_tokens, 4096)
                    map_tokens = max(map_tokens, 1024)
                return map_tokens
            def get_thinking_tokens(self):
                return self.thinking_tokens
            def get_reasoning_effort(self):
                return self.reasoning_effort

        main_model = MinimalModel()

    # Model settings checks - removed (not needed for repomap)
    # Check if deprecated remove_reasoning is set
    # if main_model.remove_reasoning is not None:
    #     io.tool_warning(
    #         "Model setting 'remove_reasoning' is deprecated, please use 'reasoning_tag' instead."
    #     )
    #
    # # Set reasoning effort and thinking tokens if specified
    # if args.reasoning_effort is not None:
    #     ...
    #
    # if args.thinking_tokens is not None:
    #     ...
    #
    # # Show warnings about unsupported settings that are being ignored
    # if args.check_model_accepts_settings:
    #     settings_to_check = [
    #         {"arg": args.reasoning_effort, "name": "reasoning_effort"},
    #         {"arg": args.thinking_tokens, "name": "thinking_tokens"},
    #     ]
    #
    #     for setting in settings_to_check:
    #         if setting["arg"] is not None and (
    #             not main_model.accepts_settings
    #             or setting["name"] not in main_model.accepts_settings
    #         ):
    #             io.tool_warning(
    #                 f"Warning: {main_model.name} does not support '{setting['name']}', ignoring."
    #             )
    #             io.tool_output(
    #                 f"Use --no-check-model-accepts-settings to force the '{setting['name']}'"
    #                 " setting."
    #             )

    # Copy-paste mode - removed
    # if args.copy_paste and args.edit_format is None:
    #     if main_model.edit_format in ("diff", "whole", "diff-fenced"):
    #         main_model.edit_format = "editor-" + main_model.edit_format

    if args.verbose:
        io.tool_output("Model metadata:")
        io.tool_output(json.dumps(main_model.info, indent=4))

        io.tool_output("Model settings:")
        for attr in sorted(fields(ModelSettings), key=lambda x: x.name):
            val = getattr(main_model, attr.name)
            val = json.dumps(val, indent=4)
            io.tool_output(f"{attr.name}: {val}")

    # Lint commands and model warnings - removed
    # lint_cmds = parse_lint_cmds(args.lint_cmd, io)
    # if lint_cmds is None:
    #     analytics.event("exit", reason="Invalid lint command format")
    #     return 1
    #
    # if args.show_model_warnings:
    #     problem = models.sanity_check_models(io, main_model)
    #     if problem:
    #         analytics.event("model warning", main_model=main_model)
    #         io.tool_output("You can skip this check with --no-show-model-warnings")
    #
    #         try:
    #             io.offer_url(urls.model_warnings, "Open documentation url for more info?")
    #             io.tool_output()
    #         except KeyboardInterrupt:
    #             analytics.event("exit", reason="Keyboard interrupt during model warnings")
    #             return 1

    repo = None
    try:
        repo = GitRepo(
            io,
            fnames,
            git_dname,
            args.asterismignore,
            subtree_only=args.subtree_only,
        )
    except FileNotFoundError:
        pass

    # if not args.skip_sanity_check_repo:
    #     if not sanity_check_repo(repo, io):
    #         analytics.event("exit", reason="Repository sanity check failed")
    #         return 1

    # if repo and not args.skip_sanity_check_repo:
    #     num_files = len(repo.get_tracked_files())
    #     analytics.event("repo", num_files=num_files)
    # else:
    #     analytics.event("no-repo")

    if args.map_tokens is None:
        map_tokens = int(main_model.get_repo_map_tokens())
    else:
        map_tokens = args.map_tokens

    if not repo:
        io.tool_error("No git repository found.")
        return 1

    # 直接创建 RepoMap（不经过 base_coder）
    repo_map_obj = RepoMap(
        map_tokens=map_tokens,
        root=repo.root,
        main_model=main_model,
        io=io,
        repo_content_prefix="以下是当前代码库的地图摘要\n",
        verbose=args.verbose,
    )

    # 获取所有跟踪文件的绝对路径
    all_abs_files = {str(Path(repo.root) / f) for f in repo.get_tracked_files()}

    # 生成 RepoMap（降级尝试）
    repo_map = repo_map_obj.get_repo_map(set(), all_abs_files)
    if repo_map:
        try:
            output_path = Path(args.output_file)
            output_path.write_text(repo_map, encoding="utf-8")

            # 从repo_map中提取统计信息（复用repomap.py的计算结果）
            stats_match = re.search(r'RepoMap尺寸统计：(\d+) tokens, (\d+) characters, ([\d.]+) KB', repo_map)
            if stats_match:
                token_count = stats_match.group(1)
                char_count = stats_match.group(2)
                file_size_kb = stats_match.group(3)
            else:
                # 备选方案：重新计算
                token_count = main_model.token_count(repo_map)
                char_count = len(repo_map)
                file_size_kb = f"{char_count / 1024:.1f}"

            io.tool_output(f"已生成 RepoMap：{output_path}")
            io.tool_output(f"RepoMap尺寸统计：{token_count} tokens, {char_count} characters, {file_size_kb} KB")
        except Exception as e:
            io.tool_error(f"写入文件失败：{e}")
            return 1


if __name__ == "__main__":
    status = main()
    sys.exit(status)
