"""Caller-selected Microsoft package versions; defaults live in the package manifest."""
import re

VERSION_OPTIONS = {
    'compiler-version': 'Microsoft.Dynamics.AX.Platform.CompilerPackage',
    'platform-version': 'Microsoft.Dynamics.AX.Platform.DevALM.BuildXpp',
    'application-version': 'Microsoft.Dynamics.AX.ApplicationSuite.DevALM.BuildXpp',
}


def add_version_options(parser):
    for option, package in VERSION_OPTIONS.items():
        parser.add_argument('--' + option, help='Select the version of ' + package)


def version_overrides(args):
    result = {}
    for option, package in VERSION_OPTIONS.items():
        value = getattr(args, option.replace('-', '_'), None)
        if value is not None:
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', value) is None:
                raise ValueError('Supply an explicit package version for --' + option)
            result[package.casefold()] = value
    return result
