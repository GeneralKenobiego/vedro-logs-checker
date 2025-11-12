from setuptools import find_packages, setup
 
def find_required():
    with open("requirements.txt") as f:
        return f.read().splitlines()
 
setup(
    name="vedro-logs-checker",
    version="0.0.4",
    description="vedro-logs-checker for the vedro.io framework",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Denis Tokarev",
    author_email="ggki4p@proton.me",
    python_requires=">=3.10",
    url="https://github.com/GeneralKenobiego/vedro-logs-checker",
    license="Apache-2.0",
    packages=find_packages(exclude=("tests",)),
    install_requires=find_required(),
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
