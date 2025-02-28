#!/bin/env python3

import argparse
import sys

from github import Auth, Github


def get_tags(
    github_client: Github,
    project: str,
    sep: str = ",",
    show_header: bool = True,
):
    """Prints date/tag combinations for all tags in the given repo

    Args:
        github_client (Github): An already authenticated github client
        project (str): The github project to use
        sep (str, optional): Seperator for each field. Defaults to ",".
        show_header (bool, optional): Whether to show a header line or not. Defaults to True.
    """
    repo = github_client.get_repo(project)
    tags = repo.get_tags()

    if show_header:
        print(f"date{sep}tag")

    i = 0
    for tag in tags:
        last_modified = tag.commit.stats.last_modified_datetime
        # We are not interested in anything older than 2024 because that's where
        # we started collecting proper build data.
        year = int(last_modified.strftime("%Y"))
        if year < 2024:
            break
        date = last_modified.strftime("%Y/%m/%d")
        line = f"{date}{sep}{tag.name}"
        print(line)


def main():
    parser = argparse.ArgumentParser(description="Get a list of tags and their dates")
    parser.add_argument(
        "--token",
        dest="token",
        type=str,
        default="YOUR-TOKEN-HERE",
        help="your github token",
    )
    parser.add_argument(
        "--project",
        dest="project",
        type=str,
        default="llvm/llvm-project",
        help="github project to use (default: llvm/llvm-project)",
    )
    parser.add_argument(
        "--separator",
        dest="separator",
        type=str,
        default=",",
        help="separator to delimit fields",
    )
    parser.add_argument(
        "--show-header",
        dest="show_header",
        action="store_true",
        help="The first row will be a header row",
    )
    args = parser.parse_args()

    github_client = Github(auth=Auth.AppAuthToken(args.token))

    get_tags(
        github_client=github_client,
        project=args.project,
        sep=args.separator,
        show_header=args.show_header,
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
