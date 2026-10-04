#!/usr/bin/python3
"""Run an installer service without a shell, then replace this process with it."""

import grp
import json
import os
import pwd
import subprocess
import sys


def main():
    with open(sys.argv[1]) as source:
        spec = json.load(source)
    user = spec.get("user")
    group = spec.get("group")
    account = (pwd.getpwuid(int(user)) if user.isdecimal() else pwd.getpwnam(user)) if user else None
    target_gid = (int(group) if group.isdecimal() else grp.getgrnam(group).gr_gid) if group else (account.pw_gid if account else os.getgid())
    if account:
        os.environ.update(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name)
        os.environ["XDG_DATA_HOME"] = os.path.join(account.pw_dir, ".local", "share")
    os.environ.update(spec.get("environment", {}))
    if os.geteuid() == 0:
        if account:
            os.initgroups(account.pw_name, target_gid)
        os.setgid(target_gid)
        if account:
            os.setuid(account.pw_uid)
    elif (account and account.pw_uid != os.geteuid()) or target_gid != os.getegid():
        raise PermissionError("Cannot change service User/Group without root")
    if spec.get("directory"):
        os.chdir(spec["directory"])
    for command in spec.get("pre", []):
        process = subprocess.run(command["argv"], check=False)
        if process.returncode and not command["ignore_failure"]:
            return process.returncode if process.returncode > 0 else 1
    os.execvpe(spec["argv"][0], spec["argv"], os.environ)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, ValueError) as error:
        print(f"run-service: {error}", file=sys.stderr)
        sys.exit(1)
