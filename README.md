# PrivateAIM Python Template

This repository serves as a template for Python-based repositories within the PrivateAIM project.
It comes preconfigured with tools for testing, building, linting and formatting your Python code.

## Prerequisites

[Poetry](https://python-poetry.org/) is the Python package manager of choice.
[Follow the installation instructions](https://python-poetry.org/docs/) and make sure that Poetry is working on your
machine.

Using [PyCharm](https://www.jetbrains.com/pycharm/) as the primary IDE is not required, but heavily encouraged.
The instructions in this document are mostly tailored towards PyCharm.

## Project setup

In GitHub, click on "Use this template", then "Create in a new repository".
Enter the name of your repository and click on "Create repository".

### With PyCharm

Go to `Git > Clone…`.
Enter the URL to the repository you just created and the directory you'd like to clone it to.
Click on `Clone`.
Confirm that you trust the project.
PyCharm will then automatically set up a new Poetry environment with all configured dependencies for your repository.
Open a terminal within PyCharm, then run `pre-commit install --install-hooks -t pre-commit -t commit-msg` to install the
pre-commit hooks.

### Manually

Clone the repository.
Open a terminal and navigate to the repository.
Run `poetry install`.
This will create a new Poetry environment and install all dependencies.
Run `poetry shell` to drop into the Poetry environment.
Finally, run `pre-commit install --install-hooks -t pre-commit -t commit-msg` to install the pre-commit hooks.

## Project structure

The [project directory](./project) is the location to put all your Python code.
Rename it to the actual name of your code project and modify the `packages` property in `pyproject.toml` accordingly.

The [tests directory](./tests) is where all your tests go.
Running `pytest` on the command line will automatically pick up any tests inside that directory and execute them.
Refer to the pytest documentation for more information on how to write your tests and get the most out of pytest.

The Poetry environment comes with these pre-installed dependencies:

- [pre-commit](https://pre-commit.com/) for pre-commit hooks
- [pytest](https://docs.pytest.org/en/7.4.x/) for testing
- [ruff](https://github.com/astral-sh/ruff) for code linting and formatting

Furthermore, thanks to pre-commit, the following hooks are installed by default:

- [out-of-the-box pre-commit hooks](https://github.com/pre-commit/pre-commit-hooks)
    - `check-added-large-files`: prevents large files from being committed
    - `check-toml`: checks TOML files for syntax errors
    - `check-yaml`: checks YAML files for syntax errors
    - `end-of-file-fixer`: checks for single newlines at the end of a file
    - `trailing-whitespace`: removes trailing whitespaces from files
- [ruff hook](https://github.com/astral-sh/ruff-pre-commit): lints and auto-formats files using ruff
- [conventional commits hook](https://github.com/compilerla/conventional-pre-commit): checks commit messages against
  the [conventional commits spec](https://www.conventionalcommits.org/en/v1.0.0/)

If any of the pre-commit hooks fail, you will have to resolve all conflicts that have been pointed out, re-add all your
previously staged files and commit again.

## Linting and auto-formatting

[Ruff](https://github.com/astral-sh/ruff) is the Python linter and formatter of choice.
It is highly recommended to install
the [Ruff plugin from the JetBrains Marketplace](https://plugins.jetbrains.com/plugin/20574-ruff).
Once installed, go to `File > Settings…`, then navigate to `Tools > Ruff`.
Make sure that "Run ruff when Reformat Code" is checked and that `Project Specific > ruff executable` points to the Ruff
executable within your virtual environment.
Next, go to `Tools > Actions on Save` and check "Reformat code".
This will automatically run Ruff on a file every time it is saved.
