"""
copr_util
"""

import functools
import logging
import os
import re

import copr.v3

import snapshot_manager.build_status as build_status


def make_client() -> copr.v3.Client:
    """
    Creates and returns a copr client to be passed along for further
    special functions.

    If the environment contains COPR_URL, COPR_LOGIN, COPR_TOKEN, and
    COPR_USERNAME, we'll try to create a Copr client from those environment
    variables; otherwise, A Copr API client is created from the config file
    in ~/.config/copr. See https://copr.fedorainfracloud.org/api/ for how to
    create such a file.
    """
    client = None
    if {"COPR_URL", "COPR_LOGIN", "COPR_TOKEN", "COPR_USERNAME"} <= set(os.environ):
        logging.debug("create copr client config from environment variables")
        config = {
            "copr_url": os.environ["COPR_URL"],
            "login": os.environ["COPR_LOGIN"],
            "token": os.environ["COPR_TOKEN"],
            "username": os.environ["COPR_USERNAME"],
        }
        client = copr.v3.Client(config)
    else:
        logging.debug("create copr client config from file")
        client = copr.v3.Client.create_from_config_file()
    return client


def project_exists(
    client: copr.v3.Client,
    ownername: str,
    projectname: str,
) -> bool:
    """Returns True if the given copr project exists; otherwise False.

    Args:
        client (copr.v3.Client): Copr client
        ownername (str): Copr owner name
        projectname (str): Copr project name

    Returns:
        bool: True if the project exists in copr; otherwise False.
    """
    try:
        client.project_proxy.get(ownername=ownername, projectname=projectname)
    except copr.v3.CoprNoResultException:
        return False
    return True


@functools.cache
def get_all_chroots(client: copr.v3.Client) -> list[str]:
    """Asks Copr to list all currently supported chroots. The response Copr will
    give varies over time whenever a new Fedora or RHEL version for example
    is released. But for our purposes, we let the function cache the results.

    Args:
        client (copr.v3.Client): A Copr client

    Returns:
        list[str]: All currently supported chroots on copr.
    """
    return client.mock_chroot_proxy.get_list().keys()


def filter_chroots(chroots: list[str], pattern: str) -> list[str]:
    """Return a sorted list of chroots filtered by the given pattern.

    Args:
        chroots (list[str]): As list of chroots to filter
        pattern (str, optional): Regular expression e.g. `r"^(fedora-(rawhide|[0-9]+)|rhel-[8,9]-)"`

    Returns:
        list[str]: List of filtered and sorted chroots.

    Examples:

    >>> chroots = ["rhel-7-x86_64", "rhel-9-s390x", "fedora-rawhide-x86_64", "centos-stream-10-ppc64le"]
    >>> filter_chroots(chroots=chroots, pattern=r"^(fedora-(rawhide|[0-9]+)|rhel-[8,9]-)")
    ['fedora-rawhide-x86_64', 'rhel-9-s390x']
    """
    res: list[str] = []
    for chroot in chroots:
        if re.match(pattern=pattern, string=chroot) != None:
            res.append(chroot)
    res.sort()
    return res


def get_all_build_states(
    client: copr.v3.Client,
    ownername: str,
    projectname: str,
) -> build_status.BuildStateList:
    """Queries all builds for the given project/owner and returns them as build statuses in a list.

    Args:
        client (copr.v3.Client): Copr client to use
        ownername (str): Copr projectname
        projectname (str): Copr ownername

    Returns:
        build_status.BuildStateList: The list of all build states for the given owner/project in copr.
    """
    states = build_status.BuildStateList()

    monitor = client.monitor_proxy.monitor(
        ownername=ownername,
        projectname=projectname,
        additional_fields=["url_build_log", "url_build"],
    )

    for package in monitor["packages"]:
        for chroot_name in package["chroots"]:
            chroot = package["chroots"][chroot_name]
            state = build_status.BuildState(
                build_id=chroot["build_id"],
                package_name=package["name"],
                chroot=chroot_name,
                url_build_log=chroot["url_build_log"],
                copr_build_state=chroot["state"],
                copr_ownername=ownername,
                copr_projectname=projectname,
            )
            if "url_build" in chroot:
                state.url_build = chroot["url_build"]

            states.append(state)
    return states


def has_all_good_builds(
    required_packages: list[str],
    required_chroots: list[str],
    states: build_status.BuildStateList,
) -> bool:
    """Check for all required combinations of successful package+chroot build states.

    Args:
        required_packages (list[str]): List of required package names.
        required_chroots (list[str]): List of required chroot names.
        states (BuildStateList): List of states to use.

    Returns:
        bool: True if all required combinations of package+chroot are in a successful state in the given `states` list.

    Example: Check with a not existing copr project

    >>> from snapshot_manager.build_status import BuildState, CoprBuildStatus
    >>> required_packages=["llvm"]
    >>> required_chroots=["fedora-rawhide-x86_64", "rhel-9-ppc64le"]
    >>> s1 = BuildState(package_name="llvm", chroot="rhel-9-ppc64le", copr_build_state=CoprBuildStatus.FORKED)
    >>> s2 = BuildState(package_name="llvm", chroot="fedora-rawhide-x86_64", copr_build_state=CoprBuildStatus.FAILED)
    >>> s3 = BuildState(package_name="llvm", chroot="fedora-rawhide-x86_64", copr_build_state=CoprBuildStatus.SUCCEEDED)
    >>> has_all_good_builds(required_packages=required_packages, required_chroots=required_chroots, states=[s1])
    False
    >>> has_all_good_builds(required_packages=required_packages, required_chroots=required_chroots, states=[s1,s2])
    False
    >>> has_all_good_builds(required_packages=required_packages, required_chroots=required_chroots, states=[s1,s2,s3])
    True
    """
    # Lists of (package,chroot) tuples
    expected: list[tuple[str, str]] = []
    actual_set: set[tuple[str, str]] = {
        (state.package_name, state.chroot) for state in states if state.is_successful
    }

    for package in required_packages:
        for chroot in required_chroots:
            expected.append((package, chroot))

    expected_set = set(expected)

    if not expected_set.issubset(actual_set):
        diff = expected_set.difference(actual_set)
        logging.error(f"These packages were not found or weren't successfull: {diff}")
        return False
    return True
