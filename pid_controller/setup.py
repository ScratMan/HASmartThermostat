import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pid_controller",
    version="0.0.1",
    author="nydegger",
    author_email="fabian.nydegger@yahoo.de",
    description="A simple PID controller",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/hirschmann/pid-autotune.git",
    packages=['pid_controller'],
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
)
