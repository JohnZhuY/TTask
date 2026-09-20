# Security Policy

## Supported versions

Security fixes are provided for the latest released version of TTask.

## Reporting a vulnerability

Please do not disclose security vulnerabilities in a public issue. Contact the
maintainer privately through the contact method listed on the maintainer's
GitHub profile. Include reproduction steps, affected versions, and the expected
impact when possible.

## Local task safety

TTask can execute commands, open files, send HTTP requests, and copy or move
files with the permissions of the current Windows user. Only create or import
tasks from sources you trust. Review command arguments, paths, URLs, and task
configuration before enabling a task.

TTask stores task configuration and execution logs locally under the current
user profile. Holiday information is downloaded when the user requests an update
or enables automatic holiday updates in the settings center.

Database restore validates SQLite integrity and the required TTask tables before
replacing local data. Holiday JSON imports are also structurally validated. A
diagnostics export contains environment/version information and aggregate counts,
but intentionally excludes task action parameters and execution-log messages.
