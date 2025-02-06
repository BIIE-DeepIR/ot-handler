# Updating the PyPI Package Version

This guide provides a concise reminder on updating your ot_handler package version for a new release on PyPI.

## 1. Git Branch Workflow for Release

- Continue your work on the `development` branch.
- When ready to release:
  - Test new released features on the robot.
  - Merge the `development` branch into `master`.
  - Update the changelog.
  - Update the version numbers.
  - (Optional) Tag the release:

    ```bash
    git checkout master
    git merge development
    git tag -a v<new_version> -m "Release version <new_version>"
    git push origin master --tags
    ```

## 2. Update Version in the Code

- Open `setup.py` and change the `version` field (e.g., from `"0.1.0"` to `"0.1.1"`).
- Update the version in `ot_handler/__init__.py` where it may be exposed.

## 3. Build and Test the Updated Package

Perform the operations in the `ot_handler` root folder.

- Upgrade your build tools:

  ```bash
  python -m pip install --upgrade setuptools wheel twine
  ```

- Build the distribution packages:

  ```bash
  python setup.py sdist bdist_wheel
  ```

- Test the installation locally by running:

  ```bash
  pip install dist/ot_handler-<new_version>-py3-none-any.whl
  ```

- Verify the update:

  ```bash
  python -c "import ot_handler; print(ot_handler.__version__)"
  ```

## 4. Upload to PyPI

- (Optional) First, upload to Test PyPI to ensure everything works:

  ```bash
  twine upload --repository-url https://test.pypi.org/legacy/ dist/*
  ```

- Then, upload the final version to the main PyPI repository:

  ```bash
  twine upload dist/*
  ```

- You will be prompted to enter your PyPI credentials.
