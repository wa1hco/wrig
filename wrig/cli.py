"""
wrig/cli.py — Command-line interface for WRIG.

Usage:
  wrig create <rig-name> [--force]
  wrig start  [<rig-name-or-prefix>]
  wrig list
  wrig delete <rig-name> [--files]
  wrig relink <rig-name>
  wrig config
  wrig completion [bash|zsh|fish]
  wrig version

Rig name convention:  <radio>[-<band>]-<mode>
  Examples: flexa-ft8   flexb-msk144   ic7300-2m-ft8   ic9700-70cm-ft4
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import wrig_config_dir, machine_config_path, templates_dir, get_instances_dir
from .instance import create_instance, delete_instance, relink_instance
from .launcher import find_existing_wsjtx_configs, start_instance
from .picker import pick_instance
from .registry import list_instances


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_create(args):
    rig = args.rig_name
    if rig.startswith("WSJT-X - "):
        rig = rig[len("WSJT-X - "):]
    create_instance(rig, force=args.force)


def cmd_start(args):
    rig_name = args.rig_name if args.rig_name else None

    # If exact match in registry, launch directly
    instances = list_instances()
    if rig_name and rig_name in instances:
        start_instance(rig_name, dry_run=args.dry_run)
        return

    # Otherwise use picker (with prefix filter if partial name given)
    selected = pick_instance(prefix=rig_name or "")
    if selected:
        start_instance(selected, dry_run=args.dry_run)


def cmd_list(args):
    instances = list_instances()
    existing = find_existing_wsjtx_configs()

    if not instances and not existing:
        print("No WRIG instances. Run: wrig create <rig-name>")
        return

    if instances:
        print(f"\n{'Rig Name':<25} {'Radio':<10} {'Band':<6} {'Mode':<10} {'Created'[:19]}")
        print(f"{'-'*25} {'-'*10} {'-'*6} {'-'*10} {'-'*19}")
        for name, info in sorted(instances.items()):
            created = info.get("created", "")[:19].replace("T", " ")
            print(f"{name:<25} {info.get('radio','?'):<10} "
                  f"{info.get('band','') or '—':<6} {info.get('mode','?'):<10} {created}")
        print()

    if existing:
        print("Discovered WSJT-X configs not yet registered with WRIG:\n")
        print(f"{'Rig Name':<25} {'Path'}")
        print(f"{'-'*25} {'-'*40}")
        for name, path in sorted(existing.items()):
            print(f"{name:<25} {path}")
        print()


def cmd_delete(args):
    if not args.yes:
        confirm = input(f"Delete instance '{args.rig_name}'? [y/N] ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
    delete_instance(args.rig_name, remove_files=args.files)


def cmd_relink(args):
    relink_instance(args.rig_name)


def cmd_config(args):
    cfg_dir = wrig_config_dir()
    machine_cfg = machine_config_path()
    tmpl_dir = templates_dir()
    inst_dir = get_instances_dir()

    print(f"\nWRIG configuration")
    print(f"  Config dir:    {cfg_dir}")
    print(f"  Machine config:{machine_cfg}")
    print(f"  Templates dir: {tmpl_dir}")
    print(f"  Instances dir: {inst_dir}")
    print()

    if machine_cfg.exists():
        print(machine_cfg.read_text())
    else:
        print("(no machine config yet — will be created on first 'wrig create' or 'wrig start')")


def cmd_completion(args):
    shell = args.shell
    script_name = "wrig"

    if shell == "bash":
        print(_bash_completion(script_name))
    elif shell == "zsh":
        print(_zsh_completion(script_name))
    elif shell == "fish":
        print(_fish_completion(script_name))
    else:
        print(f"Unknown shell '{shell}'. Supported: bash, zsh, fish")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Shell completion scripts
# ---------------------------------------------------------------------------

def _get_rig_names_for_completion() -> str:
    """Return space-separated rig names for shell completion."""
    try:
        return " ".join(sorted(list_instances().keys()))
    except Exception:
        return ""


def _bash_completion(cmd: str) -> str:
    return f'''\
# WRIG bash completion
# Add to ~/.bashrc or source from there:
#   eval "$(wrig completion bash)"

_{cmd}_completions() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}"
    local prev="${{COMP_WORDS[COMP_CWORD-1]}}"
    local commands="create start list delete relink config completion version"

    if [ "${{COMP_CWORD}}" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "${{commands}}" -- "${{cur}}") )
        return 0
    fi

    case "${{prev}}" in
        start|delete|relink)
            local instances
            instances=$({cmd} list 2>/dev/null | awk 'NR>2 && NF>0 {{print $1}}')
            COMPREPLY=( $(compgen -W "${{instances}}" -- "${{cur}}") )
            ;;
        completion)
            COMPREPLY=( $(compgen -W "bash zsh fish" -- "${{cur}}") )
            ;;
    esac
}}

complete -F _{cmd}_completions {cmd}
'''


def _zsh_completion(cmd: str) -> str:
    return f'''\
#compdef {cmd}
# WRIG zsh completion
# Add to ~/.zshrc:
#   eval "$(wrig completion zsh)"

_{cmd}() {{
    local -a commands instances
    commands=(
        'create:Create a new WSJTX instance'
        'start:Start a WSJTX instance'
        'list:List all instances'
        'delete:Delete an instance'
        'relink:Re-create shared log symlink'
        'config:Show WRIG configuration'
        'completion:Generate shell completion'
        'version:Show version'
    )

    _arguments -C \\
        '1: :->command' \\
        '*: :->args'

    case $state in
        command)
            _describe 'command' commands
            ;;
        args)
            case $words[2] in
                start|delete|relink)
                    instances=($({cmd} list 2>/dev/null | awk 'NR>2 && NF>0 {{print $1}}'))
                    _describe 'instance' instances
                    ;;
                completion)
                    _values 'shell' bash zsh fish
                    ;;
            esac
            ;;
    esac
}}

_{cmd} "$@"
'''


def _fish_completion(cmd: str) -> str:
    return f'''\
# WRIG fish completion
# Save to ~/.config/fish/completions/{cmd}.fish
# Or: wrig completion fish > ~/.config/fish/completions/{cmd}.fish

set -l commands create start list delete relink config completion version

complete -c {cmd} -f
complete -c {cmd} -n "__fish_use_subcommand" -a "$commands"

function __wrig_instances
    {cmd} list 2>/dev/null | awk 'NR>2 && NF>0 {{print $1}}'
end

complete -c {cmd} -n "__fish_seen_subcommand_from start delete relink" \\
    -a "(__wrig_instances)"
complete -c {cmd} -n "__fish_seen_subcommand_from completion" \\
    -a "bash zsh fish"
complete -c {cmd} -n "__fish_seen_subcommand_from create" \\
    -d "rig-name: <radio>[-<band>]-<mode>  e.g. flexa-ft8"
complete -c {cmd} -n "__fish_seen_subcommand_from delete" -l files \\
    -d "Also delete config directory"
complete -c {cmd} -n "__fish_seen_subcommand_from delete" -l yes \\
    -d "Skip confirmation"
complete -c {cmd} -n "__fish_seen_subcommand_from create" -l force \\
    -d "Recreate even if instance exists"
complete -c {cmd} -n "__fish_seen_subcommand_from start" -l dry-run \\
    -d "Show launch command without running"
'''


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wrig",
        description="WRIG — WSJTX Instance Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  wrig create flexa-ft8           # create instance from flexa template
  wrig create ic7300-2m-ft8       # create with radio+band+mode name
  wrig start flexa-ft8            # launch directly
  wrig start flex                 # fuzzy pick from all 'flex*' instances
  wrig start                      # show full picker
  wrig list                       # show all instances
  wrig delete flexb-msk144        # remove from registry
  wrig delete flexb-msk144 --files  # also delete config dir
  wrig relink ic7300-2m-ft8       # fix broken shared log symlink
  wrig config                     # show paths and machine config
  eval "$(wrig completion bash)"  # enable tab completion
        """
    )
    parser.add_argument("--version", action="version", version=f"wrig {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    # create
    p_create = sub.add_parser("create", help="Create a new WSJTX instance")
    p_create.add_argument("rig_name", metavar="rig-name",
                          help="e.g. flexa-ft8, ic7300-2m-ft8")
    p_create.add_argument("--force", action="store_true",
                          help="Recreate even if already exists")

    # start
    p_start = sub.add_parser("start", help="Launch a WSJTX instance")
    p_start.add_argument("rig_name", nargs="?", metavar="rig-name",
                         help="Full name or prefix (omit for interactive picker)")
    p_start.add_argument("--dry-run", action="store_true",
                         help="Print launch command without running")

    # list
    sub.add_parser("list", help="List all known instances")

    # delete
    p_del = sub.add_parser("delete", help="Delete an instance")
    p_del.add_argument("rig_name", metavar="rig-name")
    p_del.add_argument("--files", action="store_true",
                       help="Also delete the instance config directory")
    p_del.add_argument("--yes", "-y", action="store_true",
                       help="Skip confirmation prompt")

    # relink
    p_relink = sub.add_parser("relink",
                               help="Re-create shared log symlink for an instance")
    p_relink.add_argument("rig_name", metavar="rig-name")

    # config
    sub.add_parser("config", help="Show WRIG paths and machine configuration")

    # completion
    p_comp = sub.add_parser("completion", help="Output shell completion script")
    p_comp.add_argument("shell", choices=["bash", "zsh", "fish"])

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "create":     cmd_create,
        "start":      cmd_start,
        "list":       cmd_list,
        "delete":     cmd_delete,
        "relink":     cmd_relink,
        "config":     cmd_config,
        "completion": cmd_completion,
    }

    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
